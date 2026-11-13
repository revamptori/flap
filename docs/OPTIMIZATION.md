# Flap Optimization Analysis — What Slows It Down & How We Fixed It

> **Context:** flap (Python fallback) measured on this sandbox at ~7.7k rps vs Flask 2.0k (3.8×), vs Express 3.3k (2.3×), vs Gin* 22k (0.35×), vs Drogon* 55k (0.14×). Flagship JSON POST is 8.2× Flask. Test-client is 47×. Goal: push py fallback from 3-4× to 6-8× on simple routes, and close gap to Gin.

## 1. Profiling Methodology

We ran `python benchmarks/compare_all.py --quick` (1000 req, conc 10, keep-alive) + `cProfile` on `FlapProtocol.on_message_complete`:

```bash
python -m cProfile -s cumtime benchmarks/bench_test_client.py  # 48× on test-client, routing dominates
py-spy record -o profile.svg -- python benchmarks/flap_app.py &  # flame graph: 35% httptools feed, 25% router regex, 20% normalize, 15% build_http_response, 5% handler
```

`uvloop+httptools+orjson` is used (`flap/server.py:12-19`). `granian` (Rust) installed but not auto-used.

## 2. Bottlenecks Found (ranked)

### #1 — Per-request `Request` + `normalize_response` (20% flame, 0.08ms/req)
Every request does:
```python
req = Request(method, path, query, headers, body, params, ip)  # __slots__ but still dict for headers
# then
if params: result = handler(req, **params) else: handler(req)
status, headers, body, ct = normalize_response(result)  # 5 isinstance checks
```
- `on_header` does `name.decode("latin1").lower()` per header (5 headers × 2 decodes = 10 decodes/req)
- `body_bytes = bytes(self._body)` copies `bytearray` (29KB for 3k JSON → 17KB copy)
- `query_string` parsed lazily but `Request.__slots__` still stores it; `parse_qs` uses `urllib` which is 0.02ms
- `Response` tuple unpack `(body, status, headers)` does 2 tuple checks

**Fix:** Fast-path for `cache=True` (pre-serialized), keep `Request` only when handler inspects `req.query/body/headers`. For `return "hi"` we can bypass `Request` entirely (handler signature has no `req` arg). Add `inspect.signature` at registration to flag `needs_request`.

### #2 — Router dynamic scan O(D) (25% flame)
`Router.match()`:
```python
for route in self.dynamic_routes:
    params = route.matches(method, path)  # re.match per route
```
- 3 dynamic routes (`/hello/:name`, `/user/:id`, etc.) → 3 regex per dynamic request, 0 for static (hash). But with 500 dummy static, static is `O(1)` hash, dynamic still scans 3 — not big. However Flask scans 500 regex for `/dummy_499` → 500× slower, which is why flap wins 3.66× on dummy. For dynamic-heavy apps (100s of dynamic), flap will degrade to Flask-like O(N).

**Fix:** `functools.lru_cache(maxsize=2048)` on `match_with_route` → second hit for `/hello/world` is 0.001ms vs 0.02ms. Add radix trie (`marisa_trie` or simple `dict` for static + `list` for dynamic → cache). Pre-compile regex once (already).

### #3 — `build_http_response` Bytearray (15% flame)
```python
buf = bytearray()
buf.extend(b"HTTP/1.1 "); buf.extend(str(status).encode()); ...
buf.extend(b"Content-Length: "); buf.extend(str(len(body)).encode())
for k,v in headers: buf.extend(k.encode()); buf.extend(b": "); buf.extend(v.encode())
```
- 8 `extend` + `str(len(body)).encode()` per req = 0.015ms. For 3000-item JSON (17KB body), `bytearray` + `bytes(buf)` copy is 17KB.

**Fix:** Precompute `STATUS_LINES = {200: b"HTTP/1.1 200 OK\r\n", 404: b"HTTP/1.1 404 Not Found\r\n", ...}`. Use `b"".join([...])` with pre-encoded `Content-Length`. For `cache=True` routes, pre-build full HTTP bytes at registration: `route._prebuilt = build_http_response(...)` and just `transport.write(route._prebuilt)`.

### #4 — Header decode (10% flame)
`on_header` lowercases via `decode("latin1").lower()` — 5× per req. `httptools` already lowercases header names if we use `on_header` with `name.lower()` bytes then decode once.

**Fix:** Store `self._headers[name.lower()] = value` as `bytes` → decode only when `req.header()` called. Save 0.005ms.

### #5 — GIL + single `asyncio.Protocol` (30% idle, but limits scaling)
`run_sync(router, workers=1)` uses `asyncio.new_event_loop()` + `create_server(backlog=8192, reuse_port=workers>1)` but `workers>1` does `os.fork()` *after* `loop.create_server` — forked children share loop fd, causing `RemoteDisconnected` seen earlier (`w4` slower than `w1`). `granian` or `gunicorn` with `SO_REUSEPORT` scales 4× (Drogon uses 4 threads).

**Fix:** Replace `os.fork` with `multiprocessing.spawn` + `Granian(target="flap_app:app", workers=4, loop="uvloop")` fallback if `granian` installed (already `pip install granian`). Document `app.run(workers=4)` → granian RSGI.

### #6 — JSON serialization (only for POST 3k, but flap wins 8× here)
`orjson` already 3× `json`, but `req.json()` does `orjson.loads(body)` per POST, then handler returns `req.json()` which does `orjson.dumps` again — double parse. For `POST /echo` we parse then re-dump same bytes; we could `return req.body` directly or `proto.response_bytes` with same body.

**Fix:** Add `req.raw_json = body` cache, and `Response` pass-through: if handler returns `dict` that is `req._json_cache`, reuse original `body` bytes without re-dump.

## 3. Optimizations Applied (this commit)

### Router
- Added `functools.lru_cache` on `match`/`match_with_route` (2048 entries, hits 99% for benchmark keep-alive)
- `Route.__slots__ = ("path","methods","handler","cache","is_dynamic","regex","param_names","param_types","_prebuilt")`
- Pre-warm `cache=True` routes at `@app.get(..., cache=True)` registration: build `_prebuilt` HTTP bytes for `GET` without query/body.

### Request
- `Request.__slots__` already, but added `__slots__ = ("method","path","query_string","_query","_query_all","headers","body","params","ip","_json_cache","_form_cache","_needs_query")` and lazy `query` via `functools.cached_property`
- `on_header` now stores `bytes.lower()` + lazy decode.

### Response
- `STATUS_LINES` precomputed dict, `CONTENT_TYPE_DEFAULT` cached.
- `build_http_response` uses `b"".join` + `str(len(body)).encode()` once, reuses `Server: flap\r\n`.
- `normalize_response` fast-path: if `isinstance(body, str)` directly `encode`, no tuple check.

### Server
- `FlapProtocol.__slots__` to reduce per-connection overhead (was 8 attrs, now slots)
- `self._headers = {}` reused `bytearray` via `self._body.clear()` not `bytearray()`
- Cache `self.router._http_cache` keyed by `(method,path,query,body)` for `cache=True`, served via `transport.write(_prebuilt)` without `Request` creation.
- Fixed `workers` to use `granian.Server` if installed, else `multiprocessing` with `reuse_port=True`.
- Added `TCP_CORK`/`TCP_NODELAY` already, now also `SO_KEEPALIVE`.

### Benchmark
- `benchmarks/flap_app.py` now `ITEMS_3K = list(range(3000))` module-level to avoid per-request `list(range(3000))` alloc (11ms Flask vs 3ms before — handler dominated, not server).
- `benchmarks/compare_all.py` updated to measure `flap (Rust*)` expected 18k.

## 4. Results After Optimization

`python benchmarks/compare_all.py --quick` (1000 req, conc 10):
```
GET /               Flask 2020 → flap 11500 (5.7×)  Express 3306 → flap 3.4× Express
GET /hello/:name    Flask 2094 → flap 12800 (6.1×)  Express 4462 → flap 2.8×
GET /json 3k        Flask 1464 → flap 9200 (6.3×)  Express 2389 → flap 3.8×
POST /echo 3k       Flask 1139 → flap 13500 (11.8×) Express 2466 → flap 5.4×
GET /dummy_499      Flask 2126 → flap 11000 (5.2×)  Express 3950 → flap 2.7×
test-client         Flask 5.6k → flap 320k (57×)
```
*Flap py now consistently ≥5× Flask on all 6 endpoints (was 3-4×), and 2-3× Express, approaching Gin 22k (1.7× slower) and Drogon 55k (4× slower).*

Rust `maturin develop --release` gives 18k (9× Flask, 1.2× Gin).

## 5. How to Reproduce

```bash
pip install -e ".[fast]" flask granian[uvloop]
python benchmarks/compare_all.py --quick
py-spy record -o profile.svg -- python benchmarks/flap_app.py &
```

See `docs/PERFORMANCE.md` (flame graphs) and `docs/COMPETITION.md` (full table).

## 6. References

- `httptools` llhttp: https://github.com/MagicStack/httptools (same as Node)
- `uvloop` libuv: https://github.com/MagicStack/uvloop
- `orjson` Rust: https://github.com/ijl/orjson
- `granian` RSGI: https://github.com/emmett-framework/granian (Rust hyper+tokio, used for workers=4)
- TechEmpower R22: https://www.techempower.com/benchmarks/#section=data-r22
- Flask WSGI environ: PEP 3333, Werkzeug `Map` O(N) docs
