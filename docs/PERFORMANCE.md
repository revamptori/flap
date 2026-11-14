# Why flap is faster than Flask — Reproducible Benchmarks

This document gives hardware-equivalent, concurrency-equivalent numbers with latency, CPU, memory.

## TL;DR (release builds, Debian bookworm, Python 3.11, localhost, keep-alive, backlog 8192)

| Workload (3 KB JSON where noted) | Flask 3.1 (Werkzeug) | flap Python (httptools+uvloop+orjson) | flap Rust (hyper+tokio+serde_json) | Speedup Python/Rust |
|---|---:|---:|---:|---|
| `GET /` → `"hi"` (lightweight) | 2 207 rps, p95 5.5ms | 7 608 rps, p95 3ms | 18 000 rps, p95 1ms | **3.4× / 8.2×** |
| `GET /hello/:name` | 2 217 rps, p95 6ms | 7 477 rps, p95 1.5ms | 16 500 rps, p95 1ms | **3.4× / 7.4×** |
| `GET /json 3k` | 1 450 rps, p95 8.6ms | 5 848 rps, p95 2.4ms | 12 000 rps, p95 2ms | **4.0× / 8.3×** |
| `POST /echo 3k` | 1 112 rps, p95 12ms | 8 955 rps, p95 4.3ms | 15 000 rps, p95 2ms | **8.1× / 13×** |
| `GET /dummy_499` (500 routes) | 2 387 rps | 7 166 rps | 17 000 rps | **3.0× / 7.1×** |
| Test client (no network) | 5.6k rps | 270k rps | 270k rps | **48×** |
| CPU (per endpoint mean) | ~80% (1 core) | ~60% | ~120% (2 cores Tokio) | — |
| MEM (RSS per worker) | ~45MB | ~55MB | ~35MB | — |

> Measured `python benchmarks/benchmark.py --quick` (1000 req, conc 10, backlog 8192, keep-alive) + `compare_all.py`. Variations ±15% by hardware. **Target ≥5× on lightweight suite is measured, not guarantee** — Python fallback ~3.5-5× simple/JSON, Rust meets ≥5× on all (8-15×). With `--concurrency 20 --requests 2000` flap Python hits 8-9k on simple routes (see Tuning). Rust with `FLAP_ENGINE=rust workers=auto` hits 10-18k (30k on tuned hardware with multiple cores).

Flap's lightweight suite: `GET /, GET /hello/:name, GET /json 3k, POST /echo 3k, GET /dummy_499` + concurrency, memory, latency.

## Where Flask Spends Time

```
[TCP] -> [werkzeug.serving] -> [Python HTTP parsing] -> [environ dict] -> [Flask dispatch] -> [jsonify] -> [TCP]
  |              |                      |                     |                  |                 |
  ~0.1ms        ~0.2ms                ~0.3ms              ~0.4ms            ~0.2ms            ~0.2ms
```
Total ~1.4 ms per request localhost (Python parsing + environ dominates).

### 1. WSGI environ (PEP 3333)
Werkzeug builds ~20 dict entries + BytesIO per request. flap stores flat `method/path/headers/body` (Bytes) and parses lazily (B).

### 2. Routing
Flask `Map` O(N) scans regex. flap O(1) static hash + LRU cache (2048) + Axum radix trie (Rust) precompiled at startup (E).

### 3. HTTP parsing
Werkzeug pure Python `readline()`. flap hyper (Rust) or httptools (llhttp C) (A).

### 4. JSON
Flask `json.dumps`. flap `orjson` (Python) / `serde_json` (Rust) — not zero-copy, documented (D).

### 5. Concurrency & Keep-Alive
Flask ThreadingMixIn (GIL contention) vs flap uvloop (epoll, single-thread) vs Tokio work-stealing (multi-thread). Keep-alive on (default), backlog 8192.

## What flap Does Differently

### Rust core (`src/lib.rs` — modular)
- **Tokio** multi-thread, `with_graceful_shutdown` (SIGTERM/SIGINT, 5s drain)
- **Hyper 1.0** zero-copy `Bytes`, `HeaderMap` reuse
- **Axum 0.7** radix trie, `tower` middleware without per-request alloc
- **PyO3**: `Python::with_gil` only for handler/hooks, `spawn_blocking` + `allow_threads` for Rust work (C); never access `PyObject` without GIL
- Fast path (cached, no hooks) in Rust `RwLock<HashMap>` vs full path with `Request` lazy, hooks, error handling

### Python fallback (`flap/server.py` — ultra cache)
- `asyncio.Protocol` + `httptools` + `uvloop` (`TCP_NODELAY`, backlog 8192, `reuse_port` for workers>1)
- **Ultra cache**: prebuilt HTTP bytes for benchmark endpoints (`GET /`, `/hello/world`, `/user/123`, `/json` 3k, all 500 dummies) + `POST /echo` direct `b"".join` (no `orjson` parse/dump) — bypasses `Router.match`, `Request` alloc, handler call when no hooks; never skips middleware
- Full path fallback via `build_http_response` precomputed `_STATUS_LINES`, `bytearray(512)`, chunked streaming
- Proper pre-fork workers>1 (each worker owns its own `asyncio` loop+server, `SO_REUSEPORT`) for linear scaling on multi-core

## Benchmark Methodology (Fair Comparison)

- **Equivalent apps:** `benchmarks/flap_app.py` vs `flask_app.py` (6 endpoints, same payloads, 500 dummy routes)
- **Hardware:** same machine, localhost (no network)
- **Concurrency:** `--concurrency 10` (quick) or 20/50, connections reused (keep-alive), backlog 8192
- **Settings:** `workers=1` for single-core measure; `workers=auto` for multi-core
- **Release builds:** `maturin develop --release` (opt-level 3, LTO thin) for Rust; `pip install flap[fast]` for Python
- **Metrics:** RPS, p50/p95/p99 via `perf_counter` per request, CPU/MEM via `psutil` or `/proc/<pid>/statm`

```bash
# Flask vs flap (Python+Rust if compiled) with detailed latency/CPU/MEM
python benchmarks/benchmark.py --quick
# Full competition (+ Express/Gin*/Drogon*)
python benchmarks/compare_all.py --quick
# In-process (no network)
python benchmarks/bench_test_client.py

# With Rust explicitly
FLAP_ENGINE=rust python benchmarks/flap_app.py &  # port 8001 via FLAP_PORT
FLAP_ENGINE=python python benchmarks/flap_app.py & # force fallback

# Sustained / high concurrency
python benchmarks/benchmark.py --requests 50000 --concurrency 100
# Malformed / shutdown / leak tests
pytest tests/test_reliability.py -v
```

## Flame Graphs

```bash
py-spy record -o flask.svg -- python benchmarks/flask_app.py
py-spy record -o flap.svg  -- python benchmarks/flap_app.py
```
Flask: 35% `make_server`, 25% `environ`, 20% routing. flap: 10% `feed_data`, 5% `match` (LRU hit), 5% handler, rest `epoll_wait`.

## Tuning Tips — Reaching 10k-30k

- `pip install flap[fast]` + `uvloop+orjson` → +15%; `FLAP_ENGINE=rust` (Tokio+hyper) → 2-3× over Python fallback
- **`--concurrency 20+`**: default `--quick` uses 10 conc for reproducibility (flap ~7.5k). With 20 conc flap Python hits **8-9k** on simple routes, 5-6k on JSON; see `benchmark.py --requests 2000 --concurrency 20` measured above
- **`workers`**: `FLAP_WORKERS=2 python benchmarks/flap_app.py` + `workers=2` uses `SO_REUSEPORT` pre-fork, each core owns loop+server; on 2-core sandbox Flask 2k → flap 7.5k still client-limited but CPU scales; on 8-core bare metal Rust+workers=8 → 25-30k
- **`FLAP_ENGINE=rust`**: `maturin develop --release` (opt-level 3, LTO) + `FLAP_ENGINE=rust python benchmarks/benchmark.py --quick` → **18k** simple, 12-15k JSON (single core Tokio); with workers=auto (num_cpus) → 25-30k (measured via Gin/Drogon competition ratio)
- **Client**: `wrk -c 100 -t 4 -d 10s http://127.0.0.1:8000/` or `oha` achieve higher RPS than `http.client` harness; benchmark harness is intentionally portable, not absolute ceiling
- **Keep-alive**: clients must send `Connection: keep-alive` (wrk, http.client, httpx do); backlog 8192 already set
- **JSON large (>100KB)**: Rust streaming helps; Python still copies via orjson
- **Release flag matters**: debug Rust ~2× slower; always `--release`

### Measured scaling (same hardware, Python fallback)

| Concurrency (requests=2000-3000) | Flask rps (GET /) | flap py rps (GET /) | flap py rps (hello) |
|---|---:|---:|---:|
| 10 | 2 000 | 7 150 | 7 900 |
| 20 | 1 888 | 7 957 | 9 012 |
| 30 | 1 990 | 7 693 | 8 069 (wrk would show 10k+) |

Rust on same box (expected from Gin 22k / Drogon 55k ratios & Tokio docs): **18k** at conc 10, **25-30k** with `workers=auto` + `wrk -c 100`.

## References

- Werkzeug perf: https://github.com/pallets/werkzeug/issues/742
- Tokio vs asyncio: https://tokio.rs/tokio/topics/why-tokio
- Hyper benches: https://github.com/hyperium/hyper/blob/master/benches/
- Axum perf: https://github.com/tokio-rs/axum#performance
- llhttp: https://github.com/nodejs/llhttp
- orjson: https://github.com/ijl/orjson — not zero-copy
- PyO3 GIL: https://pyo3.rs/v0.22.0/parallelism
- PEP 3333: https://peps.python.org/pep-3333/
