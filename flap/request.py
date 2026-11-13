from typing import Dict, Optional, Any
try:
    import orjson as _json_lib
    _HAS_ORJSON = True
except ImportError:
    import json as _json_lib  # type: ignore
    _HAS_ORJSON = False
    _json_lib = _json_lib  # keep alias

import json
from urllib.parse import parse_qs

class Request:
    """
    Incoming HTTP request.

    Attributes:
        method: HTTP method (e.g., "GET")
        path: URL path without query string (e.g., "/user/123")
        query_string: raw query string (e.g., "a=1&b=2")
        query: dict of parsed query params (first value per key, for simplicity; use query_all for lists)
        headers: dict of lowercase header name -> value
        body: raw request body as bytes
        params: path parameters extracted by router (e.g., {"id": "123"})
        ip: client ip if available
    """
    __slots__ = ("method", "path", "query_string", "_query", "_query_all", "headers", "body", "params", "ip", "_json_cache", "_form_cache")

    def __init__(
        self,
        method: str,
        path: str,
        query_string: str = "",
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        params: Optional[Dict[str, str]] = None,
        ip: str = "",
    ):
        self.method = method.upper()
        self.path = path
        self.query_string = query_string
        self._query: Optional[Dict[str, str]] = None
        self._query_all: Optional[Dict[str, list]] = None
        self.headers = headers or {}
        self.body = body
        self.params = params or {}
        self.ip = ip
        self._json_cache = None
        self._form_cache = None

    @property
    def query(self) -> Dict[str, str]:
        """Parsed query string as simple dict (first value wins)."""
        if self._query is None:
            self._parse_query()
        return self._query  # type: ignore

    @property
    def query_all(self) -> Dict[str, list]:
        """Parsed query string preserving all values (list per key)."""
        if self._query_all is None:
            self._parse_query()
        return self._query_all  # type: ignore

    def _parse_query(self):
        if not self.query_string:
            self._query = {}
            self._query_all = {}
            return
        parsed = parse_qs(self.query_string, keep_blank_values=True)
        self._query_all = parsed
        # flatten to first value
        self._query = {k: v[0] if v else "" for k, v in parsed.items()}

    def json(self, **kwargs) -> Any:
        """Parse body as JSON. Uses orjson if available (Rust-fast)."""
        if self._json_cache is not None:
            return self._json_cache
        if not self.body:
            return None
        if _HAS_ORJSON:
            # orjson loads returns python objects; it expects bytes
            self._json_cache = _json_lib.loads(self.body)
        else:
            self._json_cache = json.loads(self.body.decode("utf-8", errors="ignore"))
        return self._json_cache

    def text(self, encoding: str = "utf-8") -> str:
        """Body as text."""
        return self.body.decode(encoding, errors="ignore")

    def form(self) -> Dict[str, str]:
        """Parse body as application/x-www-form-urlencoded"""
        if self._form_cache is not None:
            return self._form_cache
        ctype = self.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ctype:
            parsed = parse_qs(self.body.decode(), keep_blank_values=True)
            self._form_cache = {k: v[0] if v else "" for k, v in parsed.items()}
            return self._form_cache
        # fallback: if body looks like query
        parsed = parse_qs(self.body.decode(), keep_blank_values=True)
        self._form_cache = {k: v[0] if v else "" for k, v in parsed.items()}
        return self._form_cache

    def header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.headers.get(name.lower(), default)

    def __repr__(self):
        return f"<Request {self.method} {self.path}>"
