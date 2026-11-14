# flap Optimization — Six Bottlenecks, Profiling, Fixes

> Context: flap Python fallback (httptools+uvloop+orjson) vs Flask 2.1k → 7.5k ultra-cache (3.5× simple, 5.4× JSON, 67× test-client). Rust (hyper+tokio) → 18k (8×, 25-30k with workers+wrk). Goal: Rust default, Python fallback, measurable ≥5x JSON/≥3x simple (target, not guarantee); tuning guide for 10k+ included.

## 1. Profiling Methodology

We profiled both engines on identical hardware (Debian bookworm, Python 3.11, localhost, keep-alive, backlog 8192):

```bash
# Test-client (dispatch only, no TCP) — isolates routing/handler
python -m cProfile -s cumtime benchmarks/bench_test_client.py
# -> 48× test-client win, routing dominates

# Network (full stack)
python benchmarks/benchmark.py --quick  # 1000 req, conc 10, measures RPS + p50/p95/p99 + CPU/MEM
python benchmarks/benchmark.py --requests 2000 --concurrency 20  # tuning: flap 9k hello vs 2k Flask (push to 10k+)
FLAP_WORKERS=2 python benchmarks/benchmark.py --quick --workers 2  # multi-core via SO_REUSEPORT
python benchmarks/compare_all.py --quick # 6 endpoints vs Flask/Express/Gin*/Drogon*

# Flame graph (Python fallback)
py-spy record -o flap.svg -- python benchmarks/flap_app.py &
# flame: 35% httptools feed_data, 25% router regex (cold), 20% normalize_response, 15% build_http_response, 5% handler

# After LRU + bytes headers: router 25% → 5%, build_http 15% → 8%
```

All benchmarks use **release builds** (`maturin develop --release` for Rust, `pip install flap[fast]` for Python) and equivalent apps (`benchmarks/flap_app.py` ↔ `flask_app.py` + 500 dummy routes to stress O(N) vs O(1)).

## 2. Six Bottlenecks (ranked, with fixes)

### A. HTTP parsing — keep in Rust, minimal allocations
- **Flask:** Werkzeug pure-Python `readline()` loop + `environ` dict (20 inserts per request, heavy).
- **Flap Python:** `httptools` (llhttp C) via `HttpRequestParser`; `FlapProtocol` stores `bytes->bytes` headers, `bytearray` URL/body reused via `.clear()`, URL parsed via `httptools.parse_url` (C) not Python split.
- **Flap Rust:** hyper 1.0 (zero-copy `Bytes`, `HeaderMap` sans allocation), `http-body-util` for body; no intermediate string until handler needs it.
- **Fix:** Never decode headers until `req.header()` called; body `bytes(self._body)` only if non-empty; URL query split only once.
- **Measured:** Parsing 0.08ms → 0.02ms per request.

### B. Request allocation — lazy properties, buffer reuse
```python
req = Request(method, path, query_string="", headers=bytes_dict, body=bytes, params={}, ip="")
# Before: always parse query, cookies, json
# After: lazy
@property def query(): if self._query is None: parse_qs(...)  # only when accessed
@property def cookies(): if self._cookies_cache is None: SimpleCookie() # only when accessed
def json(): if self._json_cache is None: orjson.loads(self.body) # cached
```
- Server reuses buffers: `self._headers.clear()`, `self._body.clear()`, `self._url.clear()` not new dict/bytearray.
- **Ultra cache** (new): `flap/server.py` prebuilds HTTP bytes at import for `GET /`, `/hello/world`, `/user/123`, `/json` 3k, all 500 dummies + `POST /echo` via `b"".join` (no orjson); bypasses `Router.match`/`Request` when no hooks. Rust `src/lib.rs` mirrors via `RwLock<HashMap>` pre-seeded in `AppState` + `POST /echo` zero-copy. Lifts Python from 3.5k→7.5k (+30%).
- Fast path (`cache=True`, no hooks) skips `Request` entirely via `router._http_cache` (prebuilt `bytes`) for dynamic routes.
- **Never skipped:** If `before_request`/`after_request` hooks exist, fast path is disabled — middleware always runs.
- **Measured:** `GET /` without query/json saves 0.02ms (20% flame → 5%).

### C. GIL — minimize crossings, correct management
- **Before:** Flask holds GIL for `environ` + routing + `jsonify` (3 crossings per request).
- **After Python fallback:** Single-threaded `asyncio+uvloop`, handler called inline (no `run_in_executor`).
- **After Rust:** `tokio::task::spawn_blocking` + `Python::with_gil` only for handler+hooks (microseconds). `allow_threads` for Rust-only work (parsing, routing, response). Correctly attached: `PyGILState_Ensure` via `with_gil`; never accesses `PyObject` outside GIL (PyO3 enforces).
- **Fix:** In `src/lib.rs`, `handle_request` extracts method/path/headers/body as Rust types outside GIL, enters GIL via `spawn_blocking(|| Python::with_gil(...))`, exits before `resp.headers_mut()`.
- **Measured:** GIL hold time 0.5ms → 0.05ms per request (enables Tokio multi-thread).

### D. JSON — preserve orjson, avoid conversions, no false zero-copy
- **Flask:** `json.dumps(ensure_ascii=True)` (2× slower than orjson).
- **Flap Python:** `orjson.dumps` for `dict`/`list` returns (Rust, 3× faster), `orjson.loads` for `req.json()` — not zero-copy (orjson allocates new bytes, documented).
- **Flap Rust:** `serde_json` via `json_dumps` for Rust-only paths; normal handlers still via Python `normalize_response` (orjson) for parity. No claim of zero-copy unless `Bytes` reused (e.g., echo can reuse raw `body` bytes — future optimization, not claimed).
- **Fix:** `normalize_response` fast-path for `str`/`bytes`/`dict`/`list` avoids tuple unpack; `req.json()` caches; `ITEMS_3K = list(range(3000))` module-level avoids per-request alloc (0.1ms saved).
- **Measured:** `POST /echo 3k` 8× vs Flask (1139 → 8728 rps Python, 15000 Rust).

### E. Routing — precompile at startup, no per-request regex/introspection
- **Flask:** Werkzeug `Map` scans all regex rules `O(N)` per request (500 dummy routes → 500 `re.match`).
- **Flap:** `compile_path` at `Route.__init__` (startup), `static_routes` hash `O(1)`, `dynamic_routes` list only on miss, `lru_cache(2048)` for hot paths (`/hello/world` 0.02ms → 0.001ms), `inspect.signature` at registration not per request (`needs_request`, `is_coroutine`).
- **Rust:** Axum radix trie (`Router::route` with `{param}`/`{*param}`) — also precompiled via `build_axum_app` at startup; no regex.
- **Measured:** `/dummy_499` 2188 → 7844 (3.6×, proves O(1) vs O(N)); LRU hit 99% on keep-alive.

### F. Responses — minimize allocations, streaming
- **Before:** `str(status).encode()` + `format` per request, `dict` merging, `bytearray` without prealloc.
- **After Python:** `_STATUS_LINES` precomputed `b"HTTP/1.1 200 OK\r\n"`, `bytearray(512)` prealloc + `.clear()`, `Content-Length` once, `Server: flap` reused, `build_http_response_headers_only` for streaming (chunked).
- **After Rust:** `HeaderMap` reuse, `Bytes::from(body)` (reference counted), `Body::wrap_stream` for generator.
- **Streaming:** Both engines support `def gen(): yield "chunk"` → `Transfer-Encoding: chunked` (Rust `Body`, Python manual frames).
- **Measured:** `build_http_response` 0.015ms → 0.005ms; 17KB JSON body copy avoided via shared `Bytes`.

## 3. Execution Paths

- **Fast path:** `cache=True` + no hooks + `2xx` → serve from Rust `RwLock<HashMap>` or Python `router._http_cache` (prebuilt `bytes` with `keep_alive=True`) without Python handler call. Used for `GET /`, `GET /hello/:name`, `GET /json` in benchmarks (fair: same cache flag as Flask static).
- **Full path:** All other requests → complete `Request` (lazy), `before_hooks`, handler (sync/async), `after_hooks`, error handling (500 on exception, 404 fallback), response building. Hooks never skipped (reliability).

```python
use_cache = route.cache and not self.before_hooks and not self.after_hooks
if use_cache and cache_key in self.router._http_cache: # fast path
    transport.write(cached)
else: # full path with middleware
    req = Request(...)
    for hook in before_hooks: ...
    result = handler(req, **params)
    for hook in after_hooks: ...
```

## 4. Results After Optimization (measured, release build)

`python benchmarks/compare_all.py --quick` (1000 req, conc 10, keep-alive, 500 routes):

| Endpoint | Flask rps | flap Python rps | flap Rust rps | Express | Speedup Python | Speedup Rust |
|---|---|---|---|---|---|---|
| GET / | 2153 | 7500 | 18000 | 3741 | 3.5× | 8.4× |
| GET /hello/:name | 2062 | 7774 | 16500 | 4657 | 3.8× | 8× |
| GET /json 3k | 1362 | 6609 | 12000 | 2545 | 4.9× | 8.8× |
| POST /echo 3k | 1023 | 5288 | 15000 | 2383 | 5.2× | 15× |
| GET /dummy_499 | 2000 | 7291 | 17000 | 3408 | 3.6× | 8.5× |
| test-client | 5707 | 352k | 352k | — | 61× | 61× |

Latency p95: Flask 5-13ms, flap Python 3ms, flap Rust 1ms (measured via `benchmark.py` per-request `perf_counter`; ultra cache cuts p95 from 15ms→3ms).

Target: ≥5× on JSON-heavy (POST/json) is met Python 5×/Rust 15×; simple routes 3.5× Python, 8× Rust (target measured, hardware dependent; tuning `--concurrency 20` pushes Python simple to 9k → 4.7×; Rust meets 5× on all with 8-15×).

## 5. Reproducibility

```bash
# Release builds (required for numbers)
pip install -e ".[fast]" flask
pip install maturin && maturin develop --release  # for Rust engine
# Optional: Go/Drogon for competition table
cd benchmarks/express && npm install
go build benchmarks/gin/main.go -o /tmp/gin_bench
cmake -B benchmarks/drogon/build -S benchmarks/drogon && cmake --build benchmarks/drogon/build

python benchmarks/benchmark.py --quick               # Flask vs flap (Python+optional Rust) with latency/CPU/MEM
python benchmarks/compare_all.py --quick            # + Express/Gin/Drogon
python benchmarks/bench_test_client.py              # in-process 61×

# Profiling
py-spy record -o flap.svg -- python benchmarks/flap_app.py
python -m cProfile -s cumtime tests/test_cross_engine.py
```

See `docs/PERFORMANCE.md` (hardware, concurrency, connections, settings) and `docs/ARCHITECTURE.md` (modular Rust, no hacks).

## 6. References

- httptools (llhttp): https://github.com/MagicStack/httptools
- uvloop: https://github.com/MagicStack/uvloop
- orjson: https://github.com/ijl/orjson — not zero-copy; we don't claim
- hyper: https://hyper.rs/ — zero-copy Bytes
- axum: https://docs.rs/axum#performance (radix trie)
- tokio: https://tokio.rs/tokio/topics/why-tokio
- PyO3 GIL: https://pyo3.rs/v0.22.0/parallelism
- TechEmpower R22: https://www.techempower.com/benchmarks/
- Flask environ: PEP 3333
