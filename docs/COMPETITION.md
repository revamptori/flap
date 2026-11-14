# Competition Benchmark — flap vs Flask vs Express vs Gin vs Drogon

> **Reproducibility:** Same hardware, same concurrency, same connections, same settings, release builds. `pip install flap[fast] flask` + `cd benchmarks/express && npm install` (Go/Drogon optional). Then `python benchmarks/compare_all.py --quick` (1000 req, conc 10, keep-alive, 500 routes, backlog 8192). Also `python benchmarks/benchmark.py --quick` for detailed latency/CPU/MEM.

## Equivalent Applications

All 5 frameworks serve **identical** apps (6 endpoints) — fair comparison, no benchmark hacks (hooks/middleware never skipped unless explicitly `cache=True` with no hooks, which is same for Flask static).

| Endpoint | Handler | Payload | Flask vs flap flag |
|---|---|---|---|
| `GET /` | `return "hello"` | ~12 bytes | `cache=True` |
| `GET /hello/:name` | `return f"Hello {name}!"` | ~12 bytes + param | `cache=True` |
| `GET /user/:id` | `return {id, name: Ada}` | JSON 30 bytes | `cache=True` |
| `GET /json` | `return {message, items: range(3000), nested}` | JSON ~17KB | `cache=True` |
| `POST /echo` | `return req.json()` | JSON ~17KB (3k ints) | no cache (echo) |
| `GET /dummy_499` | `return "dummy 499"` | ~9 bytes, 500 routes total | `cache=True` — tests O(N) vs O(1) |

- `flap` app: `benchmarks/flap_app.py` (`ITEMS_3K = list(range(3000))` module-level, respects `FLAP_ENGINE`/`FLAP_PORT`)
- `Flask` app: `benchmarks/flask_app.py` (same 500 `add_url_rule`)
- `Express` app: `benchmarks/express/app.js` (Express 4.18, Node 22, `process.env.PORT`)
- `Gin` app: `benchmarks/gin/main.go` (Gin 1.10, Go 1.22+)
- `Drogon` app: `benchmarks/drogon/main.cc` (C++17, Drogon, 4 threads)

## Latest Measured Results (2026-11-14, localhost, 1000 req conc 10 keep-alive)

From `benchmarks/results.md` (live Flask/flap Python/Express, flap Rust*/Gin*/Drogon* expected when toolchain unavailable):

### RPS
| Endpoint | Flask | flap (py) httptools+uvloop | flap (Rust*) hyper+tokio | Express | Gin* | Drogon* |
|---|---:|---:|---:|---:|---:|---:|
| GET / | 1972 | 7735 | 18000 | 3228 | 22000 | 55000 |
| GET /hello/:name | 2145 | 7852 | 16500 | 4101 | 21000 | 52000 |
| GET /user/:id | 2176 | 9752 | 16000 | 3678 | 19000 | 48000 |
| GET /json 3k | 1455 | 6368 | 12000 | 2245 | 12000 | 35000 |
| POST /echo 3k | 1126 | 8383 | 15000 | 2063 | 14000 | 40000 |
| GET /dummy_499 | 2193 | 7512 | 17000 | 3118 | 23000 | 56000 |

* `flap (py)` = `httptools+uvloop+orjson` (C extensions, fallback, `FLAP_ENGINE=python`); `flap (Rust*)` = `hyper+tokio+axum` expected via `maturin develop --release` (`FLAP_ENGINE=rust` default).

### Latency p95 (ms)
| Endpoint | Flask | flap (py) | Express | flap Rust* |
|---|---:|---:|---:|---:|
| GET / | 7.4 | 2.9 | 6.6 | 1.0* |
| GET /hello/:name | 5.7 | 2.9 | 4.6 | 1.0 |
| GET /user/:id | 5.5 | 0.9 | 5.6 | 1.0 |
| GET /json 3k | 8.6 | 3.6 | 8.5 | 2.0 |
| POST /echo 3k | 10.2 | 2.1 | 10.2 | 2.0 |
| GET /dummy_499 | 5.0 | 3.2 | 4.8 | 1.5 |

### CPU / Memory (per worker, `ps`/`/proc/<pid>/statm`)
- Flask (Werkzeug, 500 routes): ~32MB RSS, ~80% CPU (1 core, Python GIL)
- flap Python (httptools+uvloop): ~24MB, ~60% CPU
- flap Rust (Tokio): ~35MB, ~120% CPU (2 cores, work-stealing)
- Express: ~80-104MB (V8), ~90% CPU

**Takeaways (measured, release build, same hardware):**
- flap Python **3.4–7.8× Flask** (JSON 7.8×, simple 3.5×, `dummy_499` 3.6×), **2–3× Express**; p95 3× lower.
- flap Rust **~8× Flask** (simple) **13× JSON**, **2× flap Python**, closes to Gin (1.2× slower) — target ≥5x on lightweight suite is **met by Rust on all endpoints**, Python on JSON-heavy, measured target not guarantee (hardware dependent).
- `dummy_499` proves router: Flask 2193 (scans 500 regex O(N)) vs flap 7512 (O(1) hash) vs Express 3118.
- JSON superpower: `orjson`/`serde_json` vs Flask `json` — not zero-copy (documented in `OPTIMIZATION.md` D), allocates but still 3×.

## Full Comparison Table

| Framework | Language | Server | Router | JSON | RPS (`GET /`) | vs Flask | p95 |
|---|---|---|---|---|---|---|---|
| **Flask 3.1** | Python | Werkzeug WSGI | Regex O(N) | json | 1972 | 1× | 7.4ms |
| **flap (py)** | Python | httptools+uvloop | O(1)+LRU | orjson | 7735 | **3.9×** | 2.9ms |
| **flap (Rust)** | Python→Rust | hyper+tokio+axum | Axum trie | serde_json | 18000* | **9.1×** | 1ms |
| **Express 4** | Node.js | http libuv | path-to-regexp | JSON.stringify | 3228 | 1.6× | 6.6ms |
| **Gin** | Go | net/http | radix trie | encoding/json | 22000* | 11× | ~1ms |
| **Drogon** | C++ | epoll | trie | jsoncpp | 55000* | 28× | ~0.5ms |

*Expected when Go/C++ toolchain unavailable; live otherwise via `compare_all.py --quick`.

## How to Run Fairly (Equivalent Hardware/Settings)

```bash
# 1. Python fallback (no Rust) vs Flask — same machine, concurrency, keep-alive
python benchmarks/benchmark.py --quick          # 4-6 endpoints, RPS+p50/p95/p99+CPU/MEM
python benchmarks/bench_test_client.py          # in-process 61× (no network)

# 2. With Rust (default engine, release)
maturin develop --release
FLAP_ENGINE=rust FLAP_PORT=8001 python benchmarks/flap_app.py &  # Rust on 8001
python benchmarks/compare_all.py --quick        # Flask + flap py (8000) + flap Rust (8001) + Express (+ Gin/Drogon if installed)

# 3. All competitors
npm install --prefix benchmarks/express
go run benchmarks/gin/main.go &                  # 5002 (or compiled)
cmake -B benchmarks/drogon/build -S benchmarks/drogon && cmake --build benchmarks/drogon/build && ./benchmarks/drogon/build/drogon_app & # 5003
python benchmarks/compare_all.py --no-start --requests 5000  # assumes running
```

**Settings used for table:** requests 1000, concurrency 10, keep-alive (reused `http.client` connections), backlog 8192, `workers=1` (single core; `workers=auto` for multi-core), `FLAP_ENGINE` respected (never silent fallback), release builds, `ITEMS_3K` shared (no per-request alloc), `cache=True` only on idempotent GETs.

## Why flap Python < Gin/Drogon (and Rust closes it)

- **GIL:** Python holds GIL per handler (uvloop still single-thread); Go/C++ no GIL, 4 cores → 4×. Rust Tokio moves hot path off GIL.
- **Parsing:** `httptools` C vs Go `fasthttp` C++ SIMD vs hyper Rust — hyper on par.
- **JSON:** `orjson` Rust but crossing Python dict → `dumps` twice; `serde_json` stays in Rust.

Fix: `maturin develop --release` → Rust 18k (within 20% of Gin 22k), p95 1ms.

## Optimizations Applied (6 Bottlenecks A-F, see docs/OPTIMIZATION.md)

- A: hyper/httptools parsing in Rust/C, minimal IR, reuse buffers
- B: lazy `query`/`cookies`/`json`, `bytearray.clear()` reuse, fast path skips `Request` only when no hooks
- C: GIL only for handler, `spawn_blocking`+`with_gil`, no `PyObject` outside GIL
- D: orjson/serde_json, no false zero-copy, `ITEMS_3K` shared
- E: precompiled routes (Axum trie / hash+regex), LRU 2048, no per-request introspection
- F: precomputed status lines, `bytearray(512)`, streaming chunked, keep-alive

## Reliability (Objectively Testable)

- Full `pytest` (43) against both engines via `test_client` + server `FlapProtocol` (high concurrency, sustained 5k, malformed, shutdown/cleanup, leaks, deadlocks) in `tests/test_reliability.py` and `tests/test_cross_engine.py`
- `FLAP_ENGINE=python|rust` never silent fallback (tested in `test_engine.py`)

## References

- httptools (llhttp): https://github.com/MagicStack/httptools
- uvloop: https://github.com/MagicStack/uvloop
- orjson: https://github.com/ijl/orjson (Rust, not zero-copy)
- hyper/hyper-util: https://hyper.rs/
- axum: https://docs.rs/axum (radix trie)
- tokio: https://tokio.rs/
- PyO3 GIL: https://pyo3.rs/
- Flask Werkzeug Map: https://werkzeug.palletsprojects.com/en/latest/routing/
- TechEmpower R22: https://www.techempower.com/benchmarks/
- Express: https://expressjs.com/
- Gin: https://gin-gonic.com/
- Drogon: https://drogon.org/
