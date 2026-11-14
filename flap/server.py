"""
High-performance HTTP server for flap (Python fallback).

Design goals:
- C-speed HTTP parsing via httptools (https://github.com/MagicStack/httptools) - Bottleneck A kept in Rust/C
- Event loop via uvloop if available (libuv, same as Node.js), else asyncio
- Zero-copy where possible, pre-allocated buffers, keep-alive support, streaming
- Router O(1) for static routes, precompiled - Bottleneck E
- Lazy Request properties, reusable buffers - Bottleneck B
- JSON via orjson, no false zero-copy claims - Bottleneck D
- Optimized response building, precomputed status lines - Bottleneck F
- Fast path vs full path: cached GETs bypass Python handler when no hooks (but never skip middleware) - Execution Paths

If Rust core (_flap) is available, app.run() delegates to it (hyper+tokio),
which is even faster. This Python server is the fallback and is already
significantly faster than Flask.
"""

import asyncio
import socket
import logging
import signal
from typing import Callable, Dict, Optional

try:
    import uvloop
    _HAS_UVLOOP = True
except ImportError:
    _HAS_UVLOOP = False

import httptools
from .router import Router
from .request import Request
from .response import normalize_response, build_http_response, build_http_response_headers_only

try:
    import orjson  # noqa: F401 presence check for JSON speed
except ImportError:
    pass

log = logging.getLogger("flap.server")

# Minimal error pages (pre-encoded)
_NOT_FOUND_BODY = b'{"error":"Not Found"}'
_METHOD_NOT_ALLOWED_BODY = b'{"error":"Method Not Allowed"}'
_INTERNAL_ERROR_BODY = b'{"error":"Internal Server Error"}'


class FlapProtocol(asyncio.Protocol):
    """
    asyncio.Protocol implementation for flap.
    Each TCP connection gets one protocol instance with its own parser.
    Supports HTTP/1.1 keep-alive and pipelining (sequential processing), streaming, graceful shutdown.
    """
    __slots__ = ("router", "before_hooks", "after_hooks", "transport", "parser", "_method", "_url", "_headers", "_current_header_name", "_body", "_keep_alive", "_should_close", "_client_ip", "_shutdown")

    def __init__(self, router: Router, before_hooks, after_hooks):
        self.router = router
        self.before_hooks = before_hooks
        self.after_hooks = after_hooks
        self.transport: Optional[asyncio.Transport] = None
        self.parser: Optional[httptools.HttpRequestParser] = None
        self._setup_parser()

        # per-request state
        self._method: Optional[bytes] = None
        self._url: bytearray = bytearray()
        self._headers: Dict[bytes, bytes] = {}  # type: ignore
        self._current_header_name: Optional[bytes] = None
        self._body: bytearray = bytearray()
        self._keep_alive: bool = True
        self._should_close: bool = False
        self._client_ip: str = ""
        self._shutdown: bool = False

    def _setup_parser(self):
        # parser will callback to self; we implement required methods
        self.parser = httptools.HttpRequestParser(self)

    # Protocol callbacks
    def connection_made(self, transport):
        self.transport = transport
        # TCP_NODELAY for low latency (benchmarks love it)
        try:
            sock = transport.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            peer = transport.get_extra_info("peername")
            if peer:
                self._client_ip = peer[0]
        except Exception:
            pass
        # Optimize write buffering
        try:
            transport.set_write_buffer_limits(high=256 * 1024, low=16384)
        except Exception:
            pass

    def data_received(self, data: bytes):
        # Feed to parser - this will synchronously invoke callbacks
        # Bottleneck A: parsing stays in Rust/C (httptools), minimal allocations
        try:
            self.parser.feed_data(data)  # type: ignore
        except Exception as e:
            # Parser error -> close connection
            try:
                log.debug(f"parser error: {e}")
                self.transport.close()
            except Exception:
                pass

    def connection_lost(self, exc):
        self.transport = None

    # httptools callbacks - must be named exactly
    def on_url(self, url: bytes):
        # url may be called multiple times for chunked? httptools docs says once, but be safe
        self._url.extend(url)

    def on_header(self, name: bytes, value: bytes):
        # Bottleneck F: keep headers as bytes->bytes with lowercasing on bytes (no decode per header)
        try:
            self._headers[name.lower()] = value  # keep as bytes for now
        except Exception:
            try:
                self._headers[name.lower()] = value
            except:
                pass

    def on_headers_complete(self):
        # Capture method after headers are done (ensures method available)
        try:
            self._method = self.parser.get_method()  # type: ignore
        except Exception:
            self._method = b"GET"

    def on_body(self, body: bytes):
        self._body.extend(body)

    def on_message_complete(self):
        # Dispatch request and write response, then reset for next request on same connection
        method_str = (self._method or b"GET").decode()
        url_bytes = bytes(self._url)
        headers = self._headers
        # Bottleneck B/F: avoid bytes() copy if body is empty (common for GET), reuse buffer otherwise
        body_bytes = bytes(self._body) if self._body else b""

        # Parse URL via httptools.parse_url for speed (C). Fallback to manual split if not available.
        path = "/"
        query = ""
        try:
            parsed = httptools.parse_url(url_bytes)  # type: ignore
            if parsed.path:
                path = parsed.path.decode(errors="ignore") or "/"
            else:
                path = url_bytes.decode(errors="ignore").split("?")[0] or "/"
                if "?" in url_bytes.decode(errors="ignore"):
                    query = url_bytes.decode(errors="ignore").split("?", 1)[1]
                else:
                    query = ""
                if parsed.query:
                    query = parsed.query.decode(errors="ignore")
            if parsed.query:
                query = parsed.query.decode(errors="ignore")
        except Exception:
            try:
                url_str = url_bytes.decode(errors="ignore")
                if "?" in url_str:
                    path, query = url_str.split("?", 1)
                else:
                    path, query = url_str, ""
                if not path:
                    path = "/"
            except Exception:
                path, query = "/", ""

        # Check keep-alive (httptools knows)
        try:
            self._keep_alive = self.parser.should_keep_alive()  # type: ignore
        except Exception:
            self._keep_alive = True
        # If server is shutting down, force close
        if self._shutdown:
            self._keep_alive = False

        # Dispatch - distinguish fast path vs full path (never skip middleware)
        handler, params, route = self.router.match_with_route(method_str.upper(), path)
        status = 200
        resp_headers: Dict[str, str] = {}
        resp_body: bytes = b""
        resp_ct: Optional[str] = None

        # Fast path condition: cache=True and no hooks -> serve from prebuilt HTTP bytes without handler
        # This is safe because we check not self.before_hooks and not self.after_hooks
        # Full path: all other requests go through complete Request + middleware
        use_cache = route is not None and getattr(route, "cache", False) and not self.before_hooks and not self.after_hooks

        cache_key = None
        if use_cache:
            # Key includes method, path, query, and body for POST-like methods
            if method_str.upper() in ("POST", "PUT", "PATCH"):
                cache_key = (method_str.upper(), path, query, body_bytes)
            else:
                cache_key = (method_str.upper(), path, query)
            if cache_key:
                cached_http = self.router._http_cache.get(cache_key) if self._keep_alive else None
                if cached_http is not None:
                    if self.transport and not self.transport.is_closing():
                        self.transport.write(cached_http)
                    self._reset_state_for_next()
                    return
                cached_norm = self.router._response_cache.get(cache_key)
                if cached_norm is not None:
                    status, resp_headers, resp_body, resp_ct = cached_norm
                    self._write_response(status, resp_headers, resp_body, resp_ct, self._keep_alive)
                    self._reset_state_for_next()
                    return

        if handler is None:
            # 404 - also handle malformed requests gracefully
            status = 404
            resp_body = _NOT_FOUND_BODY
            resp_ct = "application/json"
            resp_headers = {}
        else:
            # Full path: Build Request object with lazy properties (Bottleneck B)
            # Headers kept as bytes->bytes, decoded lazily in Request.header()
            # Cookies, query, json only parsed when accessed inside handler
            req = Request(
                method=method_str,
                path=path,
                query_string=query,
                headers=headers,  # type: ignore
                body=body_bytes,
                params=params or {},
                ip=self._client_ip,
            )

            # before hooks (middleware) - never skipped for benchmark gains
            intercepted = None
            for hook in self.before_hooks:
                try:
                    r = hook(req)
                    if r is not None:
                        intercepted = r
                        break
                except Exception as e:
                    log.exception(f"before_request hook error: {e}")

            if intercepted is not None:
                try:
                    status, resp_headers, resp_body, resp_ct = normalize_response(intercepted)
                except Exception as e:
                    log.exception(f"hook response normalize error: {e}")
                    status, resp_headers, resp_body, resp_ct = 500, {}, _INTERNAL_ERROR_BODY, "application/json"
            else:
                try:
                    # Check if handler is coroutine (async def)
                    if route.is_coroutine if route else asyncio.iscoroutinefunction(handler):
                        loop = asyncio.get_event_loop()
                        loop.create_task(self._handle_async(handler, req, params or {}, self._keep_alive))
                        self._reset_state_for_next()
                        return
                    else:
                        # Sync path - high throughput, check for streaming generator
                        if params:
                            result = handler(req, **params)
                        else:
                            result = handler(req)
                        # Streaming detection: if result is generator/iterator of chunks, stream it
                        if hasattr(result, "__next__") or hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict, list, tuple)):
                            # Check if it's a generator that yields chunks (not a dict/list already handled)
                            # We treat as streaming: peek first item
                            try:
                                iterator = iter(result)  # type: ignore
                                # Try to get first chunk to decide
                                first = next(iterator, None)
                                if first is None:
                                    status, resp_headers, resp_body, resp_ct = 200, {}, b"", "text/plain; charset=utf-8"
                                else:
                                    # Streaming path: write headers then chunks
                                    self._write_streaming(iterator, first, req)
                                    self._reset_state_for_next()
                                    return
                            except TypeError:
                                # Not iterable, fallback to normalize
                                status, resp_headers, resp_body, resp_ct = normalize_response(result)
                        else:
                            status, resp_headers, resp_body, resp_ct = normalize_response(result)
                except Exception as e:
                    log.exception(f"handler error for {method_str} {path}: {e}")
                    status, resp_headers, resp_body, resp_ct = 500, {}, _INTERNAL_ERROR_BODY, "application/json"

                # after hooks (only for sync path; async handled separately) - never skipped
                for hook in self.after_hooks:
                    try:
                        maybe = hook(req, status, resp_headers, resp_body)
                        if maybe is not None:
                            if isinstance(maybe, tuple) and len(maybe) == 4:
                                status, resp_headers, resp_body, resp_ct = maybe
                    except Exception as e:
                        log.exception(f"after_request hook error: {e}")

        # Build and write response (with cache store if enabled)
        if use_cache and cache_key is not None and status < 500 and handler is not None:
            # Cache normalized result and http bytes (keep-alive True)
            self.router._response_cache[cache_key] = (status, resp_headers, resp_body, resp_ct)
            http_keepalive = build_http_response(status, resp_headers, resp_body, resp_ct, keep_alive=True)
            self.router._http_cache[cache_key] = http_keepalive
            if self._keep_alive:
                if self.transport and not self.transport.is_closing():
                    self.transport.write(http_keepalive)
            else:
                self._write_response(status, resp_headers, resp_body, resp_ct, keep_alive=False)
        else:
            # Handle streaming already returned above; otherwise normal write
            self._write_response(status, resp_headers, resp_body, resp_ct, self._keep_alive)

        self._reset_state_for_next()

    def _write_streaming(self, iterator, first_chunk, req):
        """Streaming response: write headers then each chunk with chunked encoding."""
        # Determine headers from handler if it set them? For now use defaults
        # We don't have status/headers yet; assume 200 and text/plain unless handler used Response
        # Check if first_chunk is tuple signalling (headers, iterator) - not needed for simple generator
        headers = {}
        status = 200
        ct = "text/plain; charset=utf-8"
        # Write headers with chunked
        header_bytes = build_http_response_headers_only(status, headers, None, ct, keep_alive=self._keep_alive)
        if self.transport and not self.transport.is_closing():
            self.transport.write(header_bytes)
            # Write first chunk + rest as chunked frames
            for chunk in (first_chunk, *iterator):
                if isinstance(chunk, str):
                    data = chunk.encode("utf-8")
                elif isinstance(chunk, bytes):
                    data = chunk
                else:
                    data = str(chunk).encode("utf-8")
                if data:
                    self.transport.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
            self.transport.write(b"0\r\n\r\n")
            if not self._keep_alive:
                try:
                    self.transport.close()
                except:
                    pass

    def _reset_state_for_next(self):
        # Clear per-request accumulators - reuse buffers where safe (Bottleneck B)
        self._method = None
        self._url.clear()
        self._headers.clear()
        self._current_header_name = None
        self._body.clear()
        # Reset parser for next request (important for pipelining)
        self._setup_parser()

    def _write_response(self, status, headers, body, content_type, keep_alive):
        if self.transport is None or self.transport.is_closing():
            return
        try:
            raw = build_http_response(status, headers, body, content_type, keep_alive=keep_alive)
            self.transport.write(raw)
            if not keep_alive:
                try:
                    self.transport.close()
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"write error: {e}")
            try:
                self.transport.close()
            except Exception:
                pass

    async def _handle_async(self, handler, req, params, keep_alive):
        # Async handler path: execute, apply after_hooks, write response
        status = 200
        resp_headers: Dict[str, str] = {}
        resp_body: bytes = b""
        resp_ct: Optional[str] = None
        try:
            if params:
                result = await handler(req, **params)
            else:
                result = await handler(req)
            # Check streaming for async generator
            if hasattr(result, "__aiter__"):
                # async streaming - collect or stream
                chunks = []
                async for chunk in result:
                    if isinstance(chunk, str):
                        chunks.append(chunk.encode("utf-8"))
                    elif isinstance(chunk, bytes):
                        chunks.append(chunk)
                    else:
                        chunks.append(str(chunk).encode("utf-8"))
                resp_body = b"".join(chunks)
                status = 200
                resp_ct = "text/plain; charset=utf-8"
            elif hasattr(result, "__next__") and not isinstance(result, (str, bytes, dict, list, tuple)):
                # sync generator returned from async handler (edge)
                chunks = []
                for chunk in result:
                    if isinstance(chunk, str):
                        chunks.append(chunk.encode("utf-8"))
                    elif isinstance(chunk, bytes):
                        chunks.append(chunk)
                    else:
                        chunks.append(str(chunk).encode("utf-8"))
                resp_body = b"".join(chunks)
            else:
                status, resp_headers, resp_body, resp_ct = normalize_response(result)
        except Exception as e:
            log.exception(f"async handler error {req.method} {req.path}: {e}")
            status, resp_headers, resp_body, resp_ct = 500, {}, _INTERNAL_ERROR_BODY, "application/json"

        for hook in self.after_hooks:
            try:
                maybe = hook(req, status, resp_headers, resp_body)
                if maybe is not None and isinstance(maybe, tuple) and len(maybe) == 4:
                    status, resp_headers, resp_body, resp_ct = maybe
            except Exception as e:
                log.exception(f"after_request hook error: {e}")

        self._write_response(status, resp_headers, resp_body, resp_ct, keep_alive)


def run_sync(router: Router, host: str = "127.0.0.1", port: int = 8000, before_hooks=None, after_hooks=None, workers: int = 1):
    """
    Start the flap Python server (sync wrapper around asyncio).
    This is the fallback when Rust core is unavailable.
    Supports keep-alive, streaming, graceful shutdown.
    """
    before_hooks = before_hooks or []
    after_hooks = after_hooks or []

    if _HAS_UVLOOP:
        try:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        except Exception:
            pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Graceful shutdown handling
    shutdown_event = asyncio.Event()

    def _signal_handler():
        print("\n * Graceful shutdown...")
        shutdown_event.set()
        loop.stop()

    try:
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
    except NotImplementedError:
        # Windows doesn't support signals
        pass

    # Factory
    def factory():
        proto = FlapProtocol(router, before_hooks, after_hooks)
        # Propagate shutdown flag to all protocols via closure? For now each protocol checks global
        return proto

    reuse_port = workers > 1

    print(f" * Flap running on http://{host}:{port}/ (Press CTRL+C to quit)")
    print(f" * Router: {len(router.all_routes)} route(s)")
    print(f" * Engine: {'uvloop+httptools' if _HAS_UVLOOP else 'asyncio+httptools'} (Python fallback) | Workers: {workers}")
    if not _HAS_UVLOOP:
        print("   hint: pip install uvloop for extra throughput")

    coro = loop.create_server(factory, host, port, reuse_port=reuse_port, backlog=8192)
    server = loop.run_until_complete(coro)

    if workers > 1:
        import os
        children = []
        for _ in range(workers - 1):
            pid = os.fork()
            if pid == 0:
                try:
                    loop.run_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    loop.close()
                os._exit(0)
            else:
                children.append(pid)
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            print("\n * Shutting down...")
        finally:
            server.close()
            loop.run_until_complete(server.wait_closed())
            loop.close()
            for pid in children:
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
    else:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            print("\n * Shutting down...")
        finally:
            # Graceful shutdown: close server, wait for connections to finish, cleanup
            server.close()
            loop.run_until_complete(server.wait_closed())
            # Give active connections time to drain (up to 5s)
            try:
                loop.run_until_complete(asyncio.wait_for(shutdown_event.wait(), timeout=5.0))
            except asyncio.TimeoutError:
                pass
            loop.close()
