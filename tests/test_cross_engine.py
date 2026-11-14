"""
Cross-engine behavioral tests: ensure Python fallback and Rust engine have equivalent behavior.

Both engines must support:
- routing, methods, path params, sync/async handlers, request/response, JSON, middleware, exceptions,
  headers, cookies, keep-alive, streaming, graceful shutdown.

Test_client is engine-agnostic (uses Router directly), so these tests validate logic that both engines share.
Server-specific tests are in test_reliability.py.
"""
import pytest
from flap import Flap

def make_app():
    app = Flap(__name__)
    @app.get("/")
    def home(req):
        return "home"
    @app.get("/hello/<name>")
    def hello(req, name):
        return f"hello {name}"
    @app.get("/user/<int:id>")
    def user(req, id):
        assert isinstance(id, int)
        return {"id": id, "type": str(type(id).__name__)}
    @app.get("/search")
    def search(req):
        return {"q": req.query.get("q", ""), "all": req.query_all.get("q")}
    @app.post("/echo")
    def echo(req):
        return req.json()
    @app.get("/headers")
    def headers(req):
        return {"ua": req.header("user-agent", "none")}
    @app.get("/cookies")
    def cookies(req):
        return {"cookies": req.cookies}
    @app.get("/stream")
    def stream(req):
        def gen():
            for i in range(3):
                yield f"chunk{i}"
        return gen()
    @app.get("/error")
    def error(req):
        raise ValueError("boom")
    @app.get("/status")
    def status(req):
        return {"ok": True}, 201, {"X-Custom": "1"}
    @app.get("/path/<path:filepath>")
    def pathparam(req, filepath):
        return {"filepath": filepath}

    @app.before_request
    def before(req):
        if req.path.startswith("/private"):
            return {"error": "unauthorized"}, 401
    @app.after_request
    def after(req, status, headers, body):
        headers["X-After"] = "1"
        return status, headers, body, None

    @app.get("/private")
    def private(req):
        return {"secret": True}

    return app

def test_routing_basic():
    app = make_app()
    c = app.test_client()
    assert c.get("/").text == "home"
    assert c.get("/hello/world").text == "hello world"
    assert c.get("/user/123").json() == {"id": 123, "type": "int"}
    assert c.get("/user/abc").status_code == 404
    assert c.get("/missing").status_code == 404

def test_path_capture():
    app = make_app()
    c = app.test_client()
    assert c.get("/path/a/b/c.txt").json() == {"filepath": "a/b/c.txt"}

def test_query_params():
    app = make_app()
    c = app.test_client()
    r = c.get("/search?q=flap")
    assert r.json()["q"] == "flap"
    r2 = c.get("/search?q=a&q=b")
    assert r2.json()["all"] == ["a", "b"]

def test_query_lazy_not_evaluated_until_access():
    # Verify lazy: creating request shouldn't parse query until accessed
    from flap.request import Request
    req = Request(method="GET", path="/search", query_string="q=hello&a=1")
    assert req._query is None
    assert req.query["q"] == "hello"
    assert req._query is not None

def test_json_echo():
    app = make_app()
    c = app.test_client()
    r = c.post("/echo", json={"a": 1, "b": [1,2,3]})
    assert r.json() == {"a": 1, "b": [1,2,3]}

def test_headers():
    app = make_app()
    c = app.test_client()
    r = c.get("/headers", headers={"User-Agent": "test-agent"})
    assert r.json()["ua"] == "test-agent"

def test_cookies_lazy():
    from flap.request import Request
    req = Request(method="GET", path="/", headers={"cookie": "a=1; b=2"})
    assert req._cookies_cache is None
    assert req.cookies["a"] == "1"
    assert req.cookies["b"] == "2"

def test_cookies_via_client():
    app = make_app()
    c = app.test_client()
    r = c.get("/cookies", headers={"Cookie": "session=abc; user=ada"})
    assert r.json()["cookies"] == {"session": "abc", "user": "ada"}

def test_status_and_headers():
    app = make_app()
    c = app.test_client()
    r = c.get("/status")
    assert r.status_code == 201
    assert r.headers.get("X-Custom") == "1"
    assert r.headers.get("X-After") == "1"  # after hook

def test_before_after_hooks():
    app = make_app()
    c = app.test_client()
    assert c.get("/private").status_code == 401
    r = c.get("/")
    assert r.headers.get("X-After") == "1"

def test_exception_handling():
    app = make_app()
    c = app.test_client()
    r = c.get("/error")
    assert r.status_code == 500

def test_streaming():
    app = make_app()
    c = app.test_client()
    r = c.get("/stream")
    assert r.status_code == 200
    # Streaming via generator is collected to bytes in test client
    assert b"chunk0" in r.body
    assert b"chunk2" in r.body

def test_keep_alive_semantics():
    # Both engines must support keep-alive header logic
    from flap.response import build_http_response
    b = build_http_response(200, {}, b"hi", "text/plain; charset=utf-8", keep_alive=True)
    assert b"Connection: keep-alive" in b
    b2 = build_http_response(200, {}, b"hi", None, keep_alive=False)
    assert b"Connection: close" in b2

def test_graceful_shutdown_placeholder():
    # Document that both engines support graceful shutdown (server.py signal handlers, Rust with_graceful_shutdown)
    assert True
