"""
Flask-compatible globals via contextvars — makes `from flap import request` work 1:1 with Flask.

Flask uses thread-locals; flap uses contextvars (asyncio-friendly) with same semantics:
  from flap import request, g, session
  request.method, request.args, request.get_json() etc work inside handlers without passing `req`.

This is how to make syntax 1:1: handlers can be `def hello():` and use globals, or `def hello(req):` and use arg — both work.
"""
from contextvars import ContextVar
import typing

# Current request for this context (set in server.py before handler)
_current_request_ctx: ContextVar = ContextVar("_flap_request", default=None)
_current_g_ctx: ContextVar = ContextVar("_flap_g", default=None)

def _get_current_request():
    req = _current_request_ctx.get()
    if req is None:
        raise RuntimeError("Working outside of request context — no current request. Use inside a handler: def view(): request.args.get(...)")
    return req

def set_request_ctx(req):
    # returns token for reset
    g_token = _current_g_ctx.set({})
    req_token = _current_request_ctx.set(req)
    return (req_token, g_token)

def reset_request_ctx(tokens):
    req_token, g_token = tokens
    _current_request_ctx.reset(req_token)
    _current_g_ctx.reset(g_token)

class RequestProxy:
    """Proxy that looks like Flask's `request` global."""

    def _get_current(self):
        return _get_current_request()

    # Flask: request.method
    @property
    def method(self):
        return self._get_current().method
    @property
    def path(self):
        return self._get_current().path
    @property
    def url(self):
        # Flask: full URL; we approximate path + query
        req = self._get_current()
        if req.query_string:
            return f"{req.path}?{req.query_string}"
        return req.path
    @property
    def args(self):
        # Flask: CombinedMultiDict view of query params; flap: alias to query
        return self._get_current().query
    @property
    def values(self):
        # Flask: args + form
        req = self._get_current()
        v = dict(req.query)
        v.update(req.form())
        return v
    @property
    def form(self):
        return self._get_current().form()
    @property
    def json(self):
        # Flask: property (may be None)
        return self._get_current().json()
    def get_json(self, force=False, silent=False, cache=True):
        try:
            return self._get_current().json()
        except Exception:
            if silent:
                return None
            raise
    def get_data(self, as_text=False, cache=True, parse_form_data=False):
        req = self._get_current()
        if as_text:
            return req.body.decode("utf-8", errors="ignore")
        return req.body
    @property
    def data(self):
        return self._get_current().body
    @property
    def headers(self):
        # return lowercased dict for compat
        return self._get_current().headers
    @property
    def cookies(self):
        return self._get_current().cookies
    @property
    def remote_addr(self):
        return self._get_current().ip
    @property
    def ip(self):
        return self._get_current().ip
    @property
    def query_string(self):
        return self._get_current().query_string.encode() if isinstance(self._get_current().query_string, str) else self._get_current().query_string

    def __repr__(self):
        try:
            req = self._get_current()
            return f"<RequestProxy {req.method} {req.path}>"
        except:
            return "<RequestProxy (no context)>"

request = RequestProxy()

class GProxy:
    def _get_dict(self):
        d = _current_g_ctx.get()
        if d is None:
            _current_g_ctx.set({})
            return _current_g_ctx.get()
        return d
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        d = self._get_dict()
        try:
            return d[name]
        except KeyError:
            raise AttributeError(name) from None
    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._get_dict()[name] = value
    def __delattr__(self, name):
        del self._get_dict()[name]
    def get(self, key, default=None):
        return self._get_dict().get(key, default)
    def __contains__(self, key):
        return key in self._get_dict()
    def __repr__(self):
        return f"<g {self._get_dict()}>"

g = GProxy()
session = {}  # stub — Flask session is cookie-based; here we keep simple dict for API compat
