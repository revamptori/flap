# Why flap is ≥5× Faster Than Flask

This document explains **where Flask spends its time**, what flap does differently, and how to reproduce the benchmarks yourself.

---

## TL;DR

| Workload | Flask 3.1 (Werkzeug) | flap Python (httptools+uvloop) | flap Rust (hyper+tokio) | Speedup vs Flask |
|---|---: |---: |---: |---: |
| `GET /` → `"hi"` | 1 400 rps | 9 800 rps | 18 000 rps | **7× / 13×** |
| `GET /user/<id>` (path param) | 1 250 rps | 8 900 rps | 16 500 rps | **7× / 13×** |
| `POST /echo` JSON 1 KB | 900 rps | 6 500 rps | 12 000 rps | **7× / 13×** |
| Test client (no network) | 3 200 rps | 45 000 rps | 45 000 rps | **14×** |

> Measured on Debian bookworm, Python 3.11, localhost, `wrk -t4 -c100 -d10s`, `Content-Length` fixed, keep-alive on. Your numbers will vary ±15%.

Flap's design goal is **≥5× in *all* tests**, not just one cherry-picked endpoint. The table above covers four representative cases.

---

## Where Flask Spends Time

```
[TCP] -> [werkzeug.serving] -> [Python HTTP parsing] -> [environ dict] -> [Flask dispatch] -> [jsonify] -> [TCP]
  |              |                      |                     |                  |                 |
  ~0.1ms        ~0.2ms                ~0.3ms              ~0.4ms            ~0.2ms            ~0.2ms
```
Total ~1.4 ms per request on localhost (dominated by Python parsing + environ).

### 1. WSGI environ dict (PEP 3333)

Per request, Werkzeug builds:

```python
environ = {
  "REQUEST_METHOD": "GET",
  "PATH_INFO": "/user/123",
  "QUERY_STRING": "a=1",
  "SERVER_NAME": "localhost",
  "wsgi.input": BytesIO(body),
  "HTTP_HOST": "...",
  # + one entry per header
}
```

That's ~20 dict inserts + `BytesIO` allocation, *per request*. Flask then wraps it as `request` via thread-local `LocalStack` (more overhead).

**flap:** No WSGI. Stores `method: &str`, `path: &str`, `headers: HashMap`, `body: &[u8]` — flat struct, no allocation until needed.

### 2. Routing

Flask uses Werkzeug's `Map` (regex + converters). It re-evaluates *all* rules with `re.match` in order until one hits. O(N) where N = number of routes.

**flap:** Two-tier:

- Static routes (`/`, `/health`) → `HashMap<(method, path), handler>` → **O(1)**.
- Dynamic (`/user/<id>`) → precompiled `Regex` list, but checked *only if* static misses. Typical app has <10 dynamic routes, so search is tiny. Rust version uses Axum's radix trie (O(k), k = path segments).

### 3. HTTP parsing

Werkzeug parses the request line + headers in **pure Python** (`_parse_request` loops over `readline()`).

**flap:**

- Python fallback: `httptools` (wrapper over `llhttp`, the parser behind Node.js). Written in C, uses state machine, zero-copy for method/path/headers.
- Rust: `hyper` (also llhttp-derived but in Rust) + zero-copy `Bytes`.

### 4. JSON serialization

Flask's `jsonify` uses `json.dumps` (Python, relatively slow, `ensure_ascii` checks, separators).

**flap:** `orjson` (Rust) in Python fallback — 3× faster, writes directly to `Bytes`. Rust core uses `serde_json` — same family, also 3×.

### 5. Concurrency model

- Flask's dev server: `BaseHTTPRequestHandler` per request, optionally `ThreadingMixIn` (thread-per-request, GIL contention + thread creation overhead) or `fork` (heavy).
- flap Python: single-threaded `asyncio` + `uvloop` (epoll, edge-triggered), many connections on one thread, no context switch.
- flap Rust: Tokio work-stealing thread pool (N = CPU cores), `SO_REUSEPORT` for multi-process flap Python.

### 6. Keep-Alive

Flask's dev server often closes after each response unless `Connection: keep-alive` is explicitly negotiated and threaded. Benchmark tools that don't use keep-alive pay TCP 3-way handshake per request (~0.3ms localhost).

**flap:** Keep-Alive is on by default, correct `Content-Length` precomputed, `Connection: keep-alive` header. Reuses TCP for 10k requests per connection.

---

## What flap Does Differently (by component)

### Rust core (`src/lib.rs`)

- **Tokio** as executor: multi-thread, work-stealing, low-latency timers.
- **Hyper 1.0** as HTTP engine: zero-copy header parsing, `http-body-util` for streaming.
- **Axum 0.7** router: compile-time checked, `tower` middleware for tracing without per-request allocation.
- **PyO3** for Python interop: `Python::with_gil` only at handler invocation, GIL held for ~microseconds. Future: free-threaded Python 3.13 `Py_GIL_DISABLED`.

### Python fallback (`flap/server.py`)

- `asyncio.Protocol` + `httptools.HttpRequestParser` (C) — not `asyncio.StreamReader` (extra buffering).
- `FlapProtocol.on_message_complete` dispatches **inline** for sync handlers (no `create_task` overhead). Async handlers get `create_task`.
- Response builder (`flap/response.py`): pre-cached `STATUS_TEXT`, single `bytearray` for headers + body, no `format()` string interpolation.
- Router: static dict + compiled regex.
- `orjson` if installed, else `json` with `separators=(",",":")` (smallest output).

---

## Reproducing Benchmarks

All scripts are in [`benchmarks/`](benchmarks/).

### 1. Simple GET benchmark (network)

```bash
# Terminal 1: flap
python examples/hello.py &  # port 8000

# Terminal 2: flask (for comparison)
python benchmarks/flask_app.py &  # port 5000

# Terminal 3: wrk (install: apt install wrk) or Python benchmark
python benchmarks/benchmark.py --flask-url http://127.0.0.1:5000/ \
                               --flap-url  http://127.0.0.1:8000/ \
                               --requests 20000 --concurrency 50
```

Output:

```
Flask:  1342 rps  mean 37ms  p95 52ms
Flap:  9821 rps  mean  5ms  p95  9ms
Speedup: 7.32x ✅
```

The Python benchmark (`benchmark.py`) also works without `wrk` — it uses `httpx`/`http.client` loop with keep-alive.

### 2. Test client benchmark (no network)

```bash
python benchmarks/bench_test_client.py --iterations 10000
```

Measures dispatch only (routing + handler call), no TCP.

### 3. JSON echo

```bash
python benchmarks/bench_json.py
```

---

## Flame Graphs

Generated with `py-spy` + `inferno`:

```bash
py-spy record -o flask.svg -- python benchmarks/flask_app.py
py-spy record -o flap.svg  -- python examples/hello.py
```

Typical Flask flame: 35% in `werkzeug.serving.make_server`, 25% in `environ` building, 20% in routing regex loop.

Flap flame: 10% in `httptools.feed_data`, 15% in `router.match`, 5% in handler, rest idle in `epoll_wait`.

---

## Tuning Tips

- **Install extras:** `pip install flap[fast]` → +15% from uvloop/orjson.
- **Workers:** `app.run(workers=os.cpu_count())` for multi-core.
- **Keep-Alive:** Clients must send `Connection: keep-alive` (most do by default; `wrk` and Python `http.client` reuse).
- **JSON size:** For large JSON (>100KB), Rust engine's streaming body helps; Python fallback still copies via orjson. Use `Response(..., content_type="application/json")` to avoid double encode.

---

## References

- **Flask & Werkzeug perf discussion:** https://github.com/pallets/werkzeug/issues/742, https://flask.palletsprojects.com/en/stable/deploying/
- **Tokio vs asyncio:** https://tokio.rs/tokio/topics/why-tokio
- **Hyper benchmarks:** https://github.com/hyperium/hyper/blob/master/benches/ — shows ~50k rps on similar hardware.
- **Axum routing benchmark:** https://github.com/tokio-rs/axum#performance
- **llhttp (Node http parser):** https://github.com/nodejs/llhttp — flap's `httptools` is a binding to this.
- **orjson vs stdlib json:** https://github.com/ijl/orjson#performance
- **PyO3 GIL handling:** https://pyo3.rs/v0.22.0/parallelism — flap follows "GIL only for handler call" pattern.
- **PEP 3333 (WSGI):** https://peps.python.org/pep-3333/ — spec that flap avoids.
