from typing import Dict, Any, Union, Optional, Tuple
try:
    import orjson as _orjson
    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False
    _orjson = None
import json

_STATUS_TEXT = {
    100: b"Continue",
    101: b"Switching Protocols",
    200: b"OK",
    201: b"Created",
    202: b"Accepted",
    204: b"No Content",
    301: b"Moved Permanently",
    302: b"Found",
    303: b"See Other",
    304: b"Not Modified",
    307: b"Temporary Redirect",
    308: b"Permanent Redirect",
    400: b"Bad Request",
    401: b"Unauthorized",
    403: b"Forbidden",
    404: b"Not Found",
    405: b"Method Not Allowed",
    409: b"Conflict",
    422: b"Unprocessable Entity",
    429: b"Too Many Requests",
    500: b"Internal Server Error",
    502: b"Bad Gateway",
    503: b"Service Unavailable",
}

def _status_text(code: int) -> bytes:
    return _STATUS_TEXT.get(code, b"OK")

# Precompute status lines for hot path (avoid per-request str(status).encode())
_STATUS_LINES = {code: b"HTTP/1.1 " + str(code).encode() + b" " + text + b"\r\n" for code, text in _STATUS_TEXT.items()}

class Response:
    """
    Outgoing HTTP response.

    Example:
        return Response("hello", status=200)
        return Response({"msg": "ok"}, status=200)  # auto JSON
        return Response(b"raw bytes", headers={"X-Custom": "1"})

    The framework also allows returning plain primitives:
        return "hello"
        return {"key": "value"}
        return ("not found", 404)
        return ({"error": "bad"}, 400, {"X-Error": "1"})
    """
    def __init__(
        self,
        body: Any = "",
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
    ):
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.content_type = content_type

    def to_bytes_tuple(self):
        """Normalize to (status, headers_dict, body_bytes, content_type_hint)"""
        return normalize_response(self)


def jsonify(data: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> Response:
    """Helper to create JSON response."""
    return Response(body=data, status=status, headers=headers, content_type="application/json")

def redirect(url: str, status: int = 302) -> Response:
    """Helper to redirect."""
    return Response(body="", status=status, headers={"Location": url})

def normalize_response(result: Any) -> Tuple[int, Dict[str, str], bytes, Optional[str]]:
    """
    Convert handler return value into canonical tuple (status, headers, body_bytes, content_type)
    Optimized: fast-path for common str/bytes/dict without tuple check.
    """
    # Fast path: most handlers return str/dict/bytes directly (no tuple)
    # Check Response first (rare)
    if isinstance(result, Response):
        inner_status, inner_headers, inner_body, inner_ct = normalize_response(result.body)
        status = result.status if result.status else inner_status
        merged = dict(inner_headers)
        merged.update(result.headers)
        ct = result.content_type or inner_ct
        return status, merged, inner_body, ct

    if isinstance(result, str):
        # Fastest path: string -> encode
        return 200, {}, result.encode("utf-8"), "text/plain; charset=utf-8"
    if isinstance(result, bytes):
        return 200, {}, result, None
    if isinstance(result, (dict, list)):
        if _HAS_ORJSON:
            return 200, {}, _orjson.dumps(result), "application/json"
        else:
            return 200, {}, json.dumps(result, separators=(",", ":")).encode("utf-8"), "application/json"
    if result is None:
        return 200, {}, b"", "text/plain; charset=utf-8"

    # Tuple unpack for (body, status) or (body, status, headers)
    status = 200
    headers: Dict[str, str] = {}
    body = result
    content_type: Optional[str] = None

    if isinstance(result, tuple):
        if len(result) == 2:
            body, status = result
        elif len(result) == 3:
            body, status, headers = result
        else:
            raise ValueError("Invalid response tuple: expected (body, status) or (body, status, headers)")
        if headers is None:
            headers = {}
        # Recurse for body inside tuple (but avoid double recursion for Response)
        if isinstance(body, Response):
            inner_status, inner_headers, inner_body, inner_ct = normalize_response(body.body)
            status = body.status if body.status else inner_status
            merged = dict(inner_headers)
            merged.update(body.headers)
            ct = body.content_type or inner_ct
            # Merge tuple headers override as well
            merged.update(headers)
            return status, merged, inner_body, ct
        if isinstance(body, str):
            return status, headers, body.encode("utf-8"), "text/plain; charset=utf-8"
        if isinstance(body, bytes):
            return status, headers, body, None
        if isinstance(body, (dict, list)):
            if _HAS_ORJSON:
                return status, headers, _orjson.dumps(body), "application/json"
            else:
                return status, headers, json.dumps(body, separators=(",", ":")).encode("utf-8"), "application/json"
        if body is None:
            return status, headers, b"", "text/plain; charset=utf-8"
        # fallback stringify
        return status, headers, str(body).encode("utf-8"), "text/plain; charset=utf-8"

    # Fallback stringify for int etc.
    return 200, {}, str(result).encode("utf-8"), "text/plain; charset=utf-8"


def build_http_response(
    status: int,
    headers: Dict[str, str],
    body: bytes,
    content_type: Optional[str],
    keep_alive: bool = True,
    version: str = "1.1",
) -> bytes:
    """
    Build raw HTTP/1.1 response bytes. Highly optimized: uses precomputed status texts,
    minimal allocations, and avoids per-request formatting overhead where possible.
    """
    # Use precomputed status line if available (fast path)
    status_line = _STATUS_LINES.get(status)
    buf = bytearray(512)  # pre-allocate 512 bytes (typical header size)
    buf.clear()
    if status_line is not None:
        buf.extend(status_line)
    else:
        reason = _status_text(status)
        buf.extend(b"HTTP/1.1 ")
        buf.extend(str(status).encode())
        buf.extend(b" ")
        buf.extend(reason)
        buf.extend(b"\r\n")

    # Content-Type handling
    has_ct = False
    # We need to scan headers case-insensitively but we will assume lower-case check is done outside
    # For speed, just check if any header key lower == "content-type"
    # headers dict may contain mixed case; we normalize later but for now simple.
    for k in headers:
        if k.lower() == "content-type":
            has_ct = True
            break
    if not has_ct:
        if content_type:
            ct = content_type
        else:
            # infer from body if not given
            # if body looks like json? already handled, but default to text/plain for empty?
            ct = None
            # For empty body with no ct, don't send ct
            if body or status != 204:
                # Only send default if we have body or not 204
                if body.startswith(b"{") or body.startswith(b"["):
                    ct = "application/json"
        if ct:
            buf.extend(b"Content-Type: ")
            buf.extend(ct.encode())
            buf.extend(b"\r\n")

    # Content-Length
    buf.extend(b"Content-Length: ")
    buf.extend(str(len(body)).encode())
    buf.extend(b"\r\n")

    # Connection
    if keep_alive:
        buf.extend(b"Connection: keep-alive\r\n")
    else:
        buf.extend(b"Connection: close\r\n")

    # Server header (optional, for branding)
    buf.extend(b"Server: flap\r\n")

    # Custom headers
    for k, v in headers.items():
        buf.extend(k.encode())
        buf.extend(b": ")
        buf.extend(v.encode() if isinstance(v, str) else str(v).encode())
        buf.extend(b"\r\n")

    # End headers
    buf.extend(b"\r\n")
    # Body
    if body:
        buf.extend(body)
    return bytes(buf)
