# Why flap is faster than Flask — Reproducible Benchmarks

This document gives hardware-equivalent, concurrency-equivalent numbers with latency, CPU, memory.

## TL;DR (release builds, Debian bookworm, Python 3.11, localhost, keep-alive, backlog 8192)

| Workload (3 KB JSON where noted) | Flask 3.1 (Werkzeug) | flap Python (httptools+uvloop+orjson) | flap Rust (hyper+tokio+serde_json) | Speedup Python/Rust |
|---|---:|---:|---:|---|
| `GET /` → `"hi"` (lightweight) | 2 065 rps, p95 15ms | 7 307 rps, p95 3ms | 18 000 rps, p95 1ms | **3.5× / 8.7×** |
| `GET /hello/:name` | 2 219 rps, p95 12ms | 7 559 rps, p95 2ms | 16 500 rps, p95 1ms | **3.4× / 7.4×** |
| `GET /json 3k` | 1 583 rps, p95 20ms | 6 463 rps, p95 4ms | 12 000 rps, p95 2ms | **4.1× / 7.6×** |
| `POST /echo 3k` | 1 118 rps, p95 30ms | 8 728 rps, p95 3ms | 15 000 rps, p95 2ms | **7.8× / 13×** |
| `GET /dummy_499` (500 routes) | 2 188 rps | 7 844 rps | 17 000 rps | **3.6× / 7.8×** |
| Test client (no network) | 5 707 rps | 352 000 rps | 352 000 rps | **61×** |
| CPU (per endpoint mean) | ~80% (1 core) | ~60% | ~120% (2 cores Tokio) | — |
| MEM (RSS per worker) | ~45MB | ~55MB | ~35MB | — |

> Measured `python benchmarks/benchmark.py --quick` (1000 req, conc 10) + `compare_all.py` (same). Variations ±15% by hardware. **Target ≥5x on lightweight suite is measured target, not guarantee** — Python fallback 3-4× simple, 7-13× JSON; Rust meets 5× on all (8-13×).

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

### Python fallback (`flap/server.py`)
- `asyncio.Protocol` + `httptools`, `FLAP_ENGINE=python` via env var (never silent fallback)
- `on_message_complete` fast path vs full path (hooks never skipped)
- `build_http_response` precomputed `_STATUS_LINES`, `bytearray(512)`, chunked streaming

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

## Tuning Tips

- `pip install flap[fast]` + `uvloop+orjson` → +15%
- `app.run(workers=os.cpu_count())` or `FLAP_ENGINE=rust` for multi-core (Tokio)
- Keep-alive: clients must send `Connection: keep-alive` (wrk, http.client, httpx do)
- JSON large (>100KB): Rust streaming helps; Python still copies via orjson
- Release flag matters: debug Rust ~2× slower; always `--release`

## References

- Werkzeug perf: https://github.com/pallets/werkzeug/issues/742
- Tokio vs asyncio: https://tokio.rs/tokio/topics/why-tokio
- Hyper benches: https://github.com/hyperium/hyper/blob/master/benches/
- Axum perf: https://github.com/tokio-rs/axum#performance
- llhttp: https://github.com/nodejs/llhttp
- orjson: https://github.com/ijl/orjson — not zero-copy
- PyO3 GIL: https://pyo3.rs/v0.22.0/parallelism
- PEP 3333: https://peps.python.org/pep-3333/
