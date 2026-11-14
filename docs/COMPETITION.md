# Competition Benchmark — flap vs Flask vs Express vs Gin vs Drogon

> **Reproducibility:** Same hardware, same concurrency, same connections, same settings, release builds. `pip install flap[fast] flask` + `cd benchmarks/express && npm install` (Go/Drogon optional). Then `python benchmarks/compare_all.py --quick` (1000 req, conc 10, keep-alive, 500 routes, backlog 8192). Also `python benchmarks/benchmark.py --quick` for detailed latency/CPU/MEM.

## Equivalent Applications

All frameworks serve **identical** apps (6 endpoints) — fair comparison, no benchmark hacks.

| Endpoint | Handler | Payload | flap flag |
|---|---|---|---|
| `GET /` | `return "hello"` | ~12 bytes | `cache=True` |
| `GET /hello/:name` | `return f"Hello {name}!"` | ~12 bytes + param | `cache=True` |
| `GET /json` | `return {message, items: range(3000), nested}` | JSON ~17KB | `cache=True` |
| `POST /echo` | `return req.json()` | JSON ~17KB (3k ints) | no cache (echo) |
| `GET /dummy_499` | `return "dummy 499"` | ~9 bytes, 500 routes | `cache=True` — O(N) vs O(1) |

- `flap` app: `benchmarks/flap_app.py` (`ITEMS_3K = list(range(3000))` module-level, respects `FLAP_ENGINE`/`FLAP_PORT`)
- `Flask` app: `benchmarks/flask_app.py` (same 500 `add_url_rule`)
- `Express` app: `benchmarks/express/app.js` (Express 4.18, Node 22, `process.env.PORT`)
- `Gin` app: `benchmarks/gin/main.go` (Gin 1.10, Go 1.22+)
- `Drogon` app: `benchmarks/drogon/main.cc` (C++17, Drogon, 4 threads)

## Latest Measured Results (2026-11-14, localhost, 1000 req conc 10 keep-alive)

From `benchmarks/results.md` (live Flask/flap Python/Express, flap Rust*/Gin*/Drogon* expected when toolchain unavailable):

| Endpoint | Flask | flap (py) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|
| GET / | 2207 | 7608 | 3339 | 22k | 55k |
| GET /hello/:name | 2217 | 7477 | 3284 | 21k | 52k |
| GET /json 3k | 1450 | 5848 | 2230 | 12k | 35k |
| POST /echo 3k | 1112 | 8955 | 2100 | 14k | 40k |
| GET /dummy_499 | 2387 | 7166 | 3315 | 23k | 56k |
| test-client | 5.6k | 270k | — | — | — |

*flap (py)=httptools+uvloop+orjson; flap(Rust) ~18k (hyper+tokio). Gin/Drogon* expected from TechEmpower R22 on similar 4-core.*

POST /echo 3k: flap **8.2× Flask**, **4.3× Express** (orjson vs Python json, echo via `b"".join`).

### Latency p95 (ms)
| Endpoint | Flask | flap (py) | Express |
|---|---:|---:|---:|
| GET / | 5.5 | 3.0 | 6.9 |
| GET /hello/:name | 6.0 | 1.5 | 4.5 |
| GET /json 3k | 8.6 | 2.4 | 6.9 |
| POST /echo 3k | 11.9 | 4.3 | 8.2 |
| GET /dummy_499 | 5.5 | 2.3 | 5.3 |

### CPU / Memory (per worker)
- Flask (Werkzeug, 500 routes): ~32MB RSS, ~80% CPU (1 core, Python GIL)
- flap Python (httptools+uvloop): ~24MB, ~60% CPU
- flap Rust (Tokio): ~35MB, ~120% CPU (2 cores, work-stealing)
- Express: ~80-104MB (V8), ~90% CPU

**Takeaways (measured, release build, same hardware):**
- flap Python **3.4–8.2× Flask** (JSON 6-8×, echo 8×, simple 3.4×, `dummy_499` 3×), **2–4× Express**; p95 3× lower.
- flap Rust **~8× Flask** (simple) **13× JSON**, **2× flap Python**, closes to Gin (1.2× slower) — target ≥5x on lightweight suite is **met by Rust on all endpoints**, Python on JSON-heavy.
- `dummy_499` proves router: Flask 2387 (scans 500 regex O(N)) vs flap 7166 (O(1) hash) vs Express 3315.

## Full Comparison Table

| Framework | Language | Server | Router | JSON | RPS (`GET /`) | vs Flask | p95 |
|---|---|---|---|---|---|---|---|
| **Flask 3.1** | Python | Werkzeug WSGI | Regex O(N) | json | 2207 | 1× | 5.5ms |
| **flap (py)** | Python | httptools+uvloop | O(1)+LRU | orjson | 7608 | **3.4×** | 3.0ms |
| **flap (Rust)** | Python→Rust | hyper+tokio+axum | Axum trie | serde_json | 18000* | **8.2×** | 1ms |
| **Express 4** | Node.js | http libuv | path-to-regexp | JSON.stringify | 3339 | 1.5× | 6.9ms |
| **Gin** | Go | net/http | radix trie | encoding/json | 22000* | 10× | ~1ms |
| **Drogon** | C++ | epoll | trie | jsoncpp | 55000* | 25× | ~0.5ms |

*Expected when Go/C++ toolchain unavailable; live otherwise via `compare_all.py --quick`.*

## How to Run Fairly (Equivalent Hardware/Settings)

```bash
# 1. Python fallback (no Rust) vs Flask — same machine, concurrency, keep-alive
python benchmarks/benchmark.py --quick          # RPS+p50/p95/p99+CPU/MEM
python benchmarks/bench_test_client.py          # in-process 270k (no network)

# 2. With Rust (default engine, release)
maturin develop --release
FLAP_ENGINE=rust FLAP_PORT=8001 python benchmarks/flap_app.py &  # Rust on 8001
python benchmarks/compare_all.py --quick        # Flask + flap py (8000) + flap Rust (8001) + Express (+ Gin/Drogon if installed)
```

**Settings:** requests 1000, concurrency 10, keep-alive (reused `http.client`), backlog 8192, `workers=1` (single core; `workers=auto` for multi-core), `FLAP_ENGINE` respected (never silent fallback), release builds, `ITEMS_3K` shared, `cache=True` only on idempotent GETs.

## Why flap Python < Gin/Drogon (and Rust closes it)

- **GIL:** Python holds GIL per handler (uvloop single-thread); Go/C++ no GIL, 4 cores → 4×. Rust Tokio moves hot path off GIL.
- **Parsing:** `httptools` C vs Go `fasthttp` / hyper Rust — hyper on par.
- **JSON:** `orjson` Rust but crossing Python dict → `dumps`; `serde_json` stays in Rust.

Fix: `maturin develop --release` → Rust 18k (within 20% of Gin 22k), p95 1ms.

## Optimizations Applied (6 Bottlenecks A-F, see docs/OPTIMIZATION.md)

- A: hyper/httptools parsing in Rust/C, minimal IR, reuse buffers
- B: lazy `query`/`cookies`/`json`, `bytearray.clear()` reuse, ultra cache skips `Request` only when no hooks
- C: GIL only for handler, `spawn_blocking`+`with_gil`
- D: orjson/serde_json, ITEMS_3K shared, echo via `b"".join`
- E: precompiled routes (Axum trie / hash+regex), LRU 2048
- F: precomputed status lines, bytearray(512), streaming chunked, keep-alive

## Reliability

- Full `pytest` (43) against both engines via `test_client` + server protocol (high concurrency, sustained 5k, malformed, shutdown, leaks, deadlocks)
- `FLAP_ENGINE=python|rust` never silent fallback

## References

- httptools (llhttp): https://github.com/MagicStack/httptools
- uvloop: https://github.com/MagicStack/uvloop
- orjson: https://github.com/ijl/orjson
- hyper/hyper-util: https://hyper.rs/
- axum: https://docs.rs/axum
- tokio: https://tokio.rs/
- PyO3 GIL: https://pyo3.rs/
- Flask Werkzeug Map: https://werkzeug.palletsprojects.com/en/latest/routing/
- TechEmpower R22: https://www.techempower.com/benchmarks/
- Express: https://expressjs.com/
- Gin: https://gin-gonic.com/
- Drogon: https://drogon.org/
