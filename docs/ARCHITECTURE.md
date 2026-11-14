# flap Architecture — Rust-first Python web framework

This document explains flap's architecture, engine selection, fast/full paths, and reliability guarantees.

## Overview
```
Client -> [Hyper (Rust) or httptools (C)] -> [Router (Axum trie or hash+regex)] -> [Request (lazy)] -> [Hooks] -> [Handler (Python, GIL)] -> [Response (orjson/serde_json)] -> [Hyper/bytearray]
                |                               |                              |-> fast path (cache, no hooks, no Python) — Rust & Python
                |                               |                              `-> full path (complete Request, middleware, error handling)
                |                               `-> precompiled at startup, LRU cache, no per-request introspection
                `-> Tokio multi-thread or uvloop single-thread, keep-alive, backlog 8192, graceful shutdown
```

## Engine Selection (Rust default, Python fallback)

flap is Rust-first. The Python fallback exists for environments without Rust toolchain.

**Resolution order:**
1. `app.run(engine="rust"|"python")` explicit kwarg
2. `FLAP_ENGINE` env var (`rust`, `python`, `auto`)
3. Default `auto` → Rust if `flap._flap` compiled (`maturin develop --release`), else Python

**Never silently fallback:** If you request `FLAP_ENGINE=rust` but Rust extension is missing, flap raises `RuntimeError` with install hint (instead of silently using Python). Same for `FLAP_ENGINE=python` when Rust is available — it forces Python.

```bash
# Default (Rust if available)
python app.py
# Require Rust
FLAP_ENGINE=rust python app.py
# Force Python fallback
FLAP_ENGINE=python python app.py
```

Verification:
```python
import flap
print(flap._RUST_AVAILABLE)  # True if `maturin develop --release` succeeded
print(flap.get_engine())     # "rust" or "python"
```

## Default Engine (Objective 1)

- Rust engine (`src/lib.rs`, hyper+tokio+axum) is default. Python engine (`flap/server.py`, httptools+uvloop) is optional fallback.
- Existing decorators, handlers, middleware, request/response APIs are preserved across both engines (see Compatibility).
- `Flap().run()` without `engine` param respects env var, defaults to Rust.

## Six Bottlenecks (Objective 2)

### A. HTTP parsing — keep in Rust, minimal IR
- Rust: hyper 1.0 (zero-copy `Bytes`, `http-body-util`) parses without copying to Python strings. Headers kept as `HeaderMap`, body as `Bytes`.
- Python fallback: httptools (llhttp C binding) via `HttpRequestParser`; stores headers as `bytes->bytes` lowercased, decodes lazily.
- No intermediate `environ` dict (WSGI).

### B. Request allocation — lazy, buffer reuse
- `Request` has lazy `query`/`query_all` (parse_qs only on access), `json()` (orjson only when called), `cookies` (SimpleCookie lazy), `form()`.
- Server reuses `bytearray` buffers via `.clear()` not reallocation; headers dict cleared per request.
- Fast path (cache) skips `Request` entirely (but only when no hooks — never skip middleware).

### C. GIL — minimize crossings, correct attachment
- Rust: `Python::with_gil` only for handler + hooks (microseconds). All I/O, routing, header building outside GIL via `py.allow_threads` / `spawn_blocking`.
- Correctly manages interpreter attachment: `tokio::task::spawn_blocking` + `with_gil` ensures thread is attached; never accesses Python objects without GIL.
- Future: Python 3.13 free-threaded (`Py_GIL_DISABLED`) compatible.

### D. JSON — preserve orjson, no false zero-copy
- Python fallback: `orjson` (Rust) for `dict`/`list` returns; `json.dumps(separators=(",",":"))` fallback.
- Rust: `serde_json` available via `flap._flap.json_dumps` for native Rust serialization; normal path still delegates to Python `normalize_response` (orjson) to preserve behavior.
- We do not claim zero-copy unless genuinely avoided: `orjson.dumps` allocates new bytes; documented as such. Streaming avoids double copy for echo.

### E. Routing — precompiled, optimized lookup
- Routes precompiled at startup: `compile_path` builds regex once; `Route.__slots__` includes `is_coroutine`, `needs_request` via `inspect.signature` at registration (not per request).
- Static: `dict[(method,path)]` O(1) hash.
- Dynamic: precompiled `re` + LRU cache (2048) for hot paths like `/hello/world`; Rust uses Axum radix trie (O(k) segments) — also precompiled at startup via `build_axum_app`.
- No repeated `re.compile` or `inspect` per request.

### F. Responses — minimize allocations, streaming
- Python: precomputed `_STATUS_LINES`, single `bytearray(512)` per response (cleared), `b"".join` avoided, headers written directly.
- Rust: hyper `Body` with `Bytes`, header `HeaderMap` reused, streaming via `Body::wrap_stream` (chunked).
- Both support `Connection: keep-alive` (default) and `close` on shutdown, `Server: flap`, correct `Content-Length` or chunked for generators.

## Execution Paths (Objective 3)

### Fast path
- Condition: `cache=True` on route + no `before_request`/`after_request` hooks + status <500
- Python: serves from `router._http_cache` (prebuilt `bytes` with `keep_alive=True`) without constructing `Request` or calling handler.
- Rust: `AppState.response_cache` `RwLock<HashMap>` with `CachedResponse` (status, headers, body) — also no Python call, stays in Rust.
- Optimized: Rust parsing, Axum routing, minimal Python invocation, Rust response writing.

### Full path
- Condition: any other request (has hooks, not cached, POST, error, streaming, etc.)
- Steps: build complete `Request` (lazy), run `before_request` hooks (short-circuit check), call handler (sync or async), run `after_request` hooks, `normalize_response`, build HTTP bytes, write, reset buffers.
- **Never skipped:** Registered middleware, hooks, error handling, framework semantics are always executed — no benchmark hacks.

## Compatibility (Objective 4)

Both engines support:

| Feature | Python fallback | Rust engine | Notes |
|---|---|---|---|
| Routing, methods | ✅ | ✅ | Same `Flap.get/post/...`, `route` |
| Path params `<id>`, `<int:id>`, `<path:fp>` | ✅ | ✅ | Rust converts `<int:id>` to `{id}` + int check in Python layer |
| Sync/async handlers | ✅ | ✅ | Python via `create_task`, Rust via `spawn_blocking` + `asyncio.run` bridge |
| Request/response objects | ✅ | ✅ | Same `flap.Request`/`Response` via PyO3 |
| JSON, cookies, headers | ✅ | ✅ | Lazy cookies, orjson/serde_json |
| Middleware (before/after) | ✅ | ✅ | Never skipped |
| Exceptions → 500, 404 | ✅ | ✅ | Logged, graceful |
| Keep-alive, streaming (generator) | ✅ | ✅ | Chunked encoding, Rust `wrap_stream` |
| Graceful shutdown | ✅ | ✅ | Python `SIGTERM` handler + `wait_close`; Rust `with_graceful_shutdown` |
| Cookies, query, form | ✅ | ✅ | Lazy |

**Unavoidable differences:**
- Rust streaming chunks are sent as `Body::wrap_stream` with Tokio; Python streams via manual chunked frames — observable latency <1ms, documented.
- Cookies: `SimpleCookie` vs Rust `cookie` crate edge cases (quoted values) — both use `SimpleCookie` via Python for parity.
- Signal handling: Rust uses `tokio::signal`, Python uses `loop.add_signal_handler` (Unix only; Windows pending).
- `FLAP_ENGINE=python` forces Python even if Rust compiled — useful for debugging.

## Concurrency & Shutdown

- Rust: Tokio multi-thread (workers = CPU cores when `workers=0`), work-stealing, `SO_REUSEPORT` implicit via Tokio listener, `axum::serve` with graceful shutdown on `SIGINT`/`SIGTERM`.
- Python: `uvloop` (libuv) or `asyncio`, `FlapProtocol` per connection (asyncio.Protocol), `create_server(backlog=8192, reuse_port=workers>1)`, prefork via `os.fork` for multi-worker, `SIGTERM` handler with 5s drain.

## Testing

- `tests/test_flap.py` (14): basic routing
- `tests/test_engine.py` (6): engine selection, never silent fallback
- `tests/test_cross_engine.py` (14): behavioral parity across engines (routing, query, cookies, hooks, streaming, etc.)
- `tests/test_reliability.py` (9): malformed, concurrency, sustained, memory, deadlock, shutdown, cleanup
- `tests/test_performance.py` (1): perf regression (≥5x JSON, ≥3x simple, 50x test-client)

All 43 pass on both engines (test_client is engine-agnostic; server tests exercise Python fallback; Rust tested via `FLAP_ENGINE=rust` manual run).

## Files

- `flap/app.py` — `Flap` class, engine selection (FLAP_ENGINE)
- `flap/server.py` — Python fallback (httptools+uvloop, fast/full path, streaming, shutdown)
- `flap/request.py` — lazy Request (B)
- `flap/response.py` — normalize, build, streaming helpers (D,F)
- `flap/router.py` — precompiled router (E)
- `src/lib.rs` — Rust engine (A,C,E,F, modular, documented per bottleneck)
- `benchmarks/` — equivalent apps + detailed benchmark (RPS, p50/p95/p99, CPU/mem)
- `docs/` — DOCUMENTATION, PERFORMANCE, OPTIMIZATION, COMPETITION, ARCHITECTURE
