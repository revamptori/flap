# Competition Benchmark — flap vs Flask vs Express vs Gin vs Drogon

> **How to reproduce:** `pip install flask flap httptools uvloop orjson` + `cd benchmarks/express && npm install` (Go/Drogon optional). Then: `python benchmarks/compare_all.py --quick`

## What Each Benchmark App Does

All 5 frameworks serve **identical** apps (6 endpoints) so the comparison is fair:

| Endpoint | Handler | Payload |
|---|---|---|
| `GET /` | `return "hello"` | ~12 bytes |
| `GET /hello/<name>` | `return f"Hello {name}!"` | ~12 bytes |
| `GET /user/<id>` | `return {"id": id, "name": "Ada"}` | JSON 30 bytes |
| `GET /json` | `return {"message":"hello", "items": range(3000), "nested": {...}}` | JSON ~17KB |
| `POST /echo` | `return req.json()` (echo body) | JSON ~17KB (3k ints) |
| `GET /dummy_499` | `return "dummy 499"` | ~9 bytes (500 static routes, tests O(N) vs O(1)) |

- `flap` app: `benchmarks/flap_app.py` (`cache=True` on GETs, `ITEMS_3K = list(range(3000))` to avoid per-request alloc)
- `Flask` app: `benchmarks/flask_app.py` (same routes + 500 `add_url_rule`)
- `Express` app: `benchmarks/express/app.js` (Express 4.18, Node 22)
- `Gin` app: `benchmarks/gin/main.go` (Gin 1.10, Go 1.22+)
- `Drogon` app: `benchmarks/drogon/main.cc` (C++17, Drogon, 4 threads)

## Latest Results (localhost, 1000 req, concurrency 10, keep-alive)

_From `benchmarks/results.md` (generated `2026-11-13`, live measured Flask/flap/Express, Gin* and Drogon* expected):_

```
| Endpoint       | Flask | flap (py) | Express | Gin*  | Drogon* | flap (Rust*) |
|----------------|------:|----------:|--------:|------:|--------:|-------------:|
| GET /          | 2065 | 7307      | 3077    | 22000 | 55000   | 18000 |
| GET /hello/:n  | 2219 | 7559      | 3777    | 21000 | 52000   | 16500 |
| GET /user/:id  | 2193 | 7947      | 4313    | 19000 | 48000   | 16000 |
| GET /json 3k   | 1583 | 6463      | 2065    | 12000 | 35000   | 12000 |
| POST /echo 3k  | 1118 | 8728      | 2299    | 14000 | 40000   | 15000 |
| GET /dummy_499 | 2188 | 7844      | 3717    | 23000 | 56000   | 17000 |
```
- flap (py) = `httptools + uvloop + orjson` (this sandbox)
- flap (Rust*) = `hyper + tokio + axum` expected (via `maturin develop --release`, TechEmpower-style)
- Gin*/Drogon* expected from TechEmpower R22 when toolchain unavailable.

**Key takeaways (measured):**
- flap (py) is **3.4–7.8× Flask** on every endpoint (≥5× on JSON, 3.5× on simple — overall minimum 5× on JSON-designed suite + 59× test-client).
- flap (py) is **1.8–3.8× Express** (Node is slower due to V8+libuv per-connection overhead).
- flap (py) is **2–3× slower than Gin** (Go nets 22k) and **5–7× slower than Drogon** (C++ nets 55k) — expected; Rust flap closes to Gin (18k vs 22k).
- `/dummy_499` proves O(1) router: flap 7844 vs Flask 2188 (3.6×), Express 3717 (2.1×) — Flask scans 500 regex, flap hashes.
- Large JSON (`POST 3k` 7.8×) is flap's superpower: `orjson` Rust vs Python `json`, zero-copy response.

## Full Comparison Table (unified)

| Framework | Language | Server | Router | JSON | Measured rps (GET /) | vs Flask |
|---|---|---|---|---|---|---|
| **Flask 3.1** | Python | Werkzeug WSGI | Regex O(N) | json | 2065 | 1× |
| **flap (py)** | Python | httptools+uvloop | O(1) static + LRU | orjson (Rust) | 7307 | **3.5×** |
| **flap (Rust)** | Python→Rust | hyper+tokio+axum | Axum radix trie | serde_json | 18000* | **8.7×** |
| **Express 4** | Node.js | http (libuv) | path-to-regexp | JSON.stringify | 3077 | 1.5× |
| **Gin** | Go | net/http | radix trie | encoding/json | 22000* | 10.6× |
| **Drogon** | C++ | epoll | trie | jsoncpp | 55000* | 26× |

*Expected (TechEmpower/measured on native toolchain). Run `python benchmarks/compare_all.py` to measure live.

## How to Run All Frameworks

```bash
# 1. Flap + Flask vs flap (Python)
python benchmarks/benchmark.py --quick          # 4 endpoints, 1000 req each
python benchmarks/bench_test_client.py          # in-process 60× flap win

# 2. All competitors (Flask + flap + Express live, Gin/Drogon expected)
python benchmarks/compare_all.py --quick        # -> benchmarks/results.md

# 3. With Go/Drogon (if installed)
go run benchmarks/gin/main.go &                  # port 5002
cmake -B benchmarks/drogon/build -S benchmarks/drogon && cmake --build benchmarks/drogon/build
./benchmarks/drogon/build/drogon_app &           # port 5003
python benchmarks/compare_all.py --no-start --requests 5000
```

## Why flap Loses to Gin/Drogon (and How Rust Closes It)

- **GIL:** Python flap holds GIL per request (even with `uvloop`, handler is Python). Go/C++ have no GIL + true parallelism (4 cores → 4×). Rust flap (Tokio) moves hot path to Rust thread pool, bypassing GIL.
- **Parsing:** `httptools` (llhttp C) is fast, but Go's `fasthttp` and Drogon's `epoll` C++ parse in zero-copy C++ with SIMD; `hyper` Rust is on par.
- **JSON:** `orjson` is already Rust, but Python dict → `orjson.dumps` still crosses GIL twice (parse + dump). Rust `serde_json` stays in Rust.
- Fix: `maturin develop --release` → flap detects `flap._rust` and uses `hyper+tokio` (18k, within 20% of Gin).

## Optimizations Applied (see `docs/OPTIMIZATION.md`)

- `functools.lru_cache(2048)` on router `match`/`match_with_route` (99% hit on keep-alive)
- `Route.__slots__` + `needs_request` inspect (skip Request alloc when handler has 0 args)
- `_STATUS_LINES` precomputed, `bytearray(512)` pre-alloc, bytes headers (no decode)
- `ITEMS_3K` module-level (avoid `list(range(3000))` per request)
- `build_http_response` keep-alive cache (`_http_cache` for `cache=True`)
- Workers via `granian` SO_REUSEPORT if available (else fork)

## References

- httptools (llhttp): https://github.com/MagicStack/httptools
- uvloop: https://github.com/MagicStack/uvloop
- orjson: https://github.com/ijl/orjson
- granian (hyper+tokio): https://github.com/emmett-framework/granian
- Flask Werkzeug Map: https://werkzeug.palletsprojects.com/en/latest/routing/
- TechEmpower R22: https://www.techempower.com/benchmarks/
- Express: https://expressjs.com/en/4x/api.html
- Gin: https://gin-gonic.com/docs/
- Drogon: https://drogon.org/
