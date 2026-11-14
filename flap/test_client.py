from typing import Dict, Optional, Any, List
from urllib.parse import parse_qs
from .router import Router
from .request import Request
from .response import normalize_response, _STATUS_TEXT, HTTPException
try:
    from .globals import set_request_ctx, reset_request_ctx
except ImportError:
    def set_request_ctx(req): return (None, None)
    def reset_request_ctx(tok): pass

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

        # Router match with route to inspect needs_request
        handler, params, route = self.router.match_with_route(method.upper(), raw_path)
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
        tok = set_request_ctx(req)
        try:
            # before hooks — support Flask def before(): and Flap def before(req):
            intercepted = None
            intercepted_status = None
            for hook in self.before_hooks:
                try:
                    try:
                        r = hook(req)
                    except TypeError:
                        r = hook()
                    if r is not None:
                        intercepted = r
                        break
                except HTTPException as e:
                    intercepted = e.description.encode()
                    intercepted_status = e.status
                    break
                except Exception as e:
                    return TestResponse(500, {}, b'{"error":"Before hook failed"}', "application/json")

            if intercepted is not None:
                if intercepted_status is not None:
                    status, resp_headers, resp_body, resp_ct = intercepted_status, {}, intercepted if isinstance(intercepted, bytes) else str(intercepted).encode(), "text/plain"
                else:
                    status, resp_headers, resp_body, resp_ct = normalize_response(intercepted)
            else:
                try:
                    needs_req = getattr(route, "needs_request", True)
                    import asyncio
                    if asyncio.iscoroutinefunction(handler):
                        loop = asyncio.new_event_loop()
                        try:
                            if needs_req:
                                if params:
                                    result = loop.run_until_complete(handler(req, **params))
                                else:
                                    result = loop.run_until_complete(handler(req))
                            else:
                                if params:
                                    result = loop.run_until_complete(handler(**params))
                                else:
                                    result = loop.run_until_complete(handler())
                        finally:
                            loop.close()
                        status, resp_headers, resp_body, resp_ct = normalize_response(result)
                    else:
                        if needs_req:
                            if params:
                                result = handler(req, **params)
                            else:
                                result = handler(req)
                        else:
                            if params:
                                result = handler(**params)
                            else:
                                result = handler()
                        # streaming generator in test client: collect
                        if hasattr(result, "__next__") or (hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict, list, tuple, TestResponse))):
                            try:
                                chunks = []
                                for chunk in result:  # type: ignore
                                    if isinstance(chunk, str):
                                        chunks.append(chunk.encode())
                                    elif isinstance(chunk, bytes):
                                        chunks.append(chunk)
                                    else:
                                        chunks.append(str(chunk).encode())
                                status, resp_headers, resp_body, resp_ct = 200, {}, b"".join(chunks), "text/plain; charset=utf-8"
                            except TypeError:
                                status, resp_headers, resp_body, resp_ct = normalize_response(result)
                        else:
                            status, resp_headers, resp_body, resp_ct = normalize_response(result)
                except HTTPException as e:
                    return TestResponse(e.status, {}, e.description.encode(), "text/plain")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return TestResponse(500, {}, b'{"error":"Internal Server Error"}', "application/json")

                # after hooks — both signatures
                for hook in self.after_hooks:
                    try:
                        try:
                            maybe = hook(req, status, resp_headers, resp_body)
                        except TypeError:
                            maybe = hook(status)
                        if maybe is not None and isinstance(maybe, tuple) and len(maybe) == 4:
                            status, resp_headers, resp_body, resp_ct = maybe
                    except HTTPException as e:
                        status, resp_headers, resp_body, resp_ct = e.status, {}, e.description.encode(), "text/plain"
                        break
                    except Exception:
                        pass
            return TestResponse(status, resp_headers, resp_body, resp_ct)
        finally:
            reset_request_ctx(tok)

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
