from typing import Dict, Optional, Any, List
from urllib.parse import parse_qs
from .router import Router
from .request import Request
from .response import normalize_response, _STATUS_TEXT

class TestResponse:
    """In-process response for TestClient (mirrors Flask's test response but minimal)"""
    def __init__(self, status: int, headers: Dict[str, str], body: bytes, content_type: Optional[str]):
        self.status_code = status
        self.status_text = _STATUS_TEXT.get(status, b"").decode()
        self.headers = headers
        self.body = body
        self.content_type = content_type

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="ignore")

    def json(self):
        import json
        try:
            import orjson
            return orjson.loads(self.body) if self.body else None
        except ImportError:
            return json.loads(self.body.decode()) if self.body else None

    def __repr__(self):
        return f"<TestResponse {self.status_code} {len(self.body)} bytes>"

class TestClient:
    """
    Synchronous in-process test client - no network, no WSGI, direct dispatch.
    This is where flap shines vs Flask: Flask's test client builds WSGI environ
    dict (heavy), flap just constructs Request and calls handler (microseconds).

    Usage:
        app = Flap()
        @app.get("/hello/<name>")
        def hello(req, name):
            return f"hello {name}"

        client = app.test_client()
        resp = client.get("/hello/world")
        assert resp.status_code == 200
        assert resp.text == "hello world"

        # Query and headers
        resp = client.get("/search?q=flap&lang=en")
        resp = client.post("/echo", json={"a": 1})
        resp = client.request("GET", "/path", headers={"X-Token": "123"})
    """
    def __init__(self, router: Router, before_hooks: List, after_hooks: List):
        self.router = router
        self.before_hooks = before_hooks
        self.after_hooks = after_hooks

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        json: Optional[Any] = None,
        query_string: Optional[str] = None,
        **kwargs,
    ) -> TestResponse:
        # Normalize path split query
        raw_path = path
        qs = ""
        if "?" in path:
            raw_path, qs = path.split("?", 1)
        if query_string is not None:
            qs = query_string

        # Prepare body
        if json is not None:
            try:
                import orjson
                body = orjson.dumps(json)
                headers = headers or {}
                # set content-type if not already
                has_ct = any(k.lower() == "content-type" for k in headers)
                if not has_ct:
                    headers["Content-Type"] = "application/json"
            except ImportError:
                import json as j
                body = j.dumps(json).encode()
                headers = headers or {}
                has_ct = any(k.lower() == "content-type" for k in headers)
                if not has_ct:
                    headers["Content-Type"] = "application/json"
        elif body is None:
            body = b""
        elif isinstance(body, str):
            body = body.encode()
        elif isinstance(body, (dict, list)):
            # fallback json
            import json as j
            body = j.dumps(body).encode()
            headers = headers or {}
            has_ct = any(k.lower() == "content-type" for k in headers) if headers else False
            if not has_ct:
                headers["Content-Type"] = "application/json"

        # Normalize headers lowercasing is not needed for test client but keep for consistency
        headers_lc = {k.lower(): v for k, v in (headers or {}).items()}

        # Router match
        handler, params = self.router.match(method.upper(), raw_path)
        if handler is None:
            return TestResponse(404, {}, b'{"error":"Not Found"}', "application/json")

        req = Request(
            method=method,
            path=raw_path,
            query_string=qs,
            headers=headers_lc,
            body=body,
            params=params or {},
            ip="127.0.0.1",
        )

        # before hooks
        intercepted = None
        for hook in self.before_hooks:
            try:
                r = hook(req)
                if r is not None:
                    intercepted = r
                    break
            except Exception as e:
                # return 500 for hook error
                return TestResponse(500, {}, b'{"error":"Before hook failed"}', "application/json")

        if intercepted is not None:
            status, resp_headers, resp_body, resp_ct = normalize_response(intercepted)
        else:
            try:
                # Handle both sync and async handlers (test client is sync, so we run async via loop if needed)
                import asyncio
                if asyncio.iscoroutinefunction(handler):
                    # Run async handler in new loop
                    loop = asyncio.new_event_loop()
                    try:
                        if params:
                            result = loop.run_until_complete(handler(req, **params))
                        else:
                            result = loop.run_until_complete(handler(req))
                    finally:
                        loop.close()
                    status, resp_headers, resp_body, resp_ct = normalize_response(result)
                else:
                    if params:
                        result = handler(req, **params)
                    else:
                        result = handler(req)
                    status, resp_headers, resp_body, resp_ct = normalize_response(result)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return TestResponse(500, {}, b'{"error":"Internal Server Error"}', "application/json")

            # after hooks
            for hook in self.after_hooks:
                try:
                    maybe = hook(req, status, resp_headers, resp_body)
                    if maybe is not None and isinstance(maybe, tuple) and len(maybe) == 4:
                        status, resp_headers, resp_body, resp_ct = maybe
                except Exception:
                    pass

        return TestResponse(status, resp_headers, resp_body, resp_ct)

    # Sugar methods
    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def head(self, path: str, **kwargs):
        return self.request("HEAD", path, **kwargs)
