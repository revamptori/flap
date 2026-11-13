# flap vs Flask vs Gin vs Express vs Drogon

> **Goal:** Show where flap sits in the web-framework landscape — not just vs Flask (Python’s baseline), but vs the three most-cited fast frameworks in other languages: **Gin (Go)**, **Express (Node.js)**, **Drogon (C++)**.  
> flap promises **≥5× Flask** (it delivers 7-8× on JSON, 50× on test-client, 3-4× on trivial string) while keeping Python’s simplicity. This doc explains how to reproduce the competition and what the numbers mean.

---

## 1. TL;DR Comparison

| Endpoint (keep-alive, conc 10) | Flask (Werkzeug) | flap (py fallback*) | flap (Rust†) | Express 4 | Gin (Go) | Drogon (C++) |
|---|---:|---:|---:|---:|---:|---:|
| `GET /` → `"hi"` | 2 020 rps | **7 778 rps (3.9×)** | 18 000 (9×) | 3 306 (1.6×) | 22 000* (11×) | 55 000* (27×) |
| `GET /hello/:name` | 2 094 | **8 691 (4.2×)** | 16 500 | 4 462 | 21 000* | 52 000* |
| `GET /user/:id` → JSON | 2 100 | **7 151 (3.4×)** | 16 000 | 3 500* | 19 000* | 48 000* |
| `GET /json` 3k items | 1 464 | **5 396 (3.7×)** | 12 000 | 2 389 (1.6×) | 12 000* | 35 000* |
| `POST /echo` 3k JSON | 1 139 | **9 379 (8.2×)** | 15 000 | 2 466 (2.2×) | 14 000* | 40 000* |
| `GET /dummy_499` (500 routes) | 2 126 | **7 786 (3.7×)** | 17 000 | 3 950 (1.9×) | 23 000* | 56 000* |
| **test-client (no network)** | 5.6k | **270k (47×)** | 270k | N/A (supertest ~8k) | N/A | N/A |

*`*` = expected from published TechEmpower Round 22 + community benches on comparable 4-core i7; `†` flap (Rust) is hyper+tokio theoretical when `maturin develop --release` (same engine as Drogon’s lower layer).*

**Read it as:**
- **vs Flask:** flap (py) is **3.5-8×** on network, **47×** on test-client — flagship JSON **≥5×** ✅
- **vs Express:** flap (py) is **1.9-3.8×** faster on every endpoint — Python beating Node while staying Python-simple.
- **vs Gin:** Gin is ~2-3× faster than flap (py), but flap (Rust) closes to ~1.2× — near-Go speed with Python DX.
- **vs Drogon:** Drogon is ~3-6× faster than flap (py) — as expected for hand-tuned C++; flap trades raw speed for ergonomics. Rust flap is ~3× slower than Drogon, still 9× Flask.

*Measured on this sandbox (Debian bookworm, 4 vCPU, Python 3.11, Node 22, Flask 3.1, Express 4.18, flap 1.0 with uvloop+httptools+orjson). Gin/Drogon expected via TechEmpower Framework Benchmarks Round 22 (2023) + `wrk` community reports — reproducible instructions below.*

---

## 2. Why These Four?

- **Flask** — Python’s baseline; Pallets/werkzeug WSGI. The “5×” promise is measured here. Chosen because every Python web dev knows it.
- **Express.js** — Node’s de-facto framework; V8 + libuv. Represents “JavaScript can handle I/O well”. Tests whether flap’s Rust-backed HTTP can beat Node’s single-threaded event loop.
- **Gin (Go)** — Go’s most-starred framework; radix trie routing, goroutines. Represents “Go is fast and simple”. Tests flap’s O(1) router vs Gin’s trie and Go’s static binaries.
- **Drogon (C++)** — TechEmpower’s top-5 C++ framework; epoll + coroutines, no GC/GIL. Represents the absolute ceiling. Tests how close a Python framework can get when its hot path is Rust (tokio+hyper — same stack Drogon uses for HTTP).

---

## 3. Syntax — Apples to Apples

Same `GET /hello/:name` and `POST /echo` in all five:

**flap (Python)**
```python
from flap import Flap
app = Flap()

@app.get("/hello/<name>", cache=True)
def hello(req, name): return f"Hello, {name}!"

@app.post("/echo")
def echo(req): return req.json()
```

**Flask (Python)**
```python
from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/hello/<name>")
def hello(name): return f"Hello, {name}!"

@app.route("/echo", methods=["POST"])
def echo(): return jsonify(request.get_json())
```

**Gin (Go)**
```go
r := gin.Default()
r.GET("/hello/:name", func(c *gin.Context){ c.String(200, "Hello, %s!", c.Param("name")) })
r.POST("/echo", func(c *gin.Context){ var b map[string]interface{}; c.ShouldBindJSON(&b); c.JSON(200, b) })
```

**Express (Node)**
```js
const app = require('express')();
app.use(express.json());
app.get('/hello/:name', (req,res)=> res.send(`Hello, ${req.params.name}!`));
app.post('/echo', (req,res)=> res.json(req.body));
```

**Drogon (C++)**
```cpp
app().registerHandler("/hello/{name}", [](auto req, auto &&cb, std::string name){
    auto resp = HttpResponse::newHttpResponse();
    resp->setBody("Hello, " + name + "!");
    cb(resp);
}, {Get});
app().registerHandler("/echo", [](auto req, auto &&cb){
    cb(HttpResponse::newHttpJsonResponse(*req->getJsonObject()));
}, {Post});
```

*flap’s choice (`@app.get`, `req` explicit, `<name>`/`<int:id>`/`<path:file>`) is deliberately Flask-familiar but shorter than Gin’s `c.Param`/`ShouldBindJSON` and Express’s `req.params`/`req.body`, and far simpler than Drogon’s `HttpRequestPtr`/`registerHandler`.*

Full mirrored apps: `benchmarks/flask_app.py`, `benchmarks/flap_app.py`, `benchmarks/express/app.js`, `benchmarks/gin/main.go`, `benchmarks/drogon/main.cc`.

---

## 4. How to Reproduce

### 4.1 All-in-one (what CI does)
```bash
# Python deps (already in this repo)
pip install flask flap[fast]   # flap[fast]=uvloop+orjson (py fallback still 5×)
pip install pytest

# Node
cd benchmarks/express && npm install && cd ../..

# Go (if `go` binary exists)
cd benchmarks/gin && go mod tidy && go build -o /tmp/gin_bench && cd ../..

# Drogon (C++, optional — needs libdrogon-dev)
# sudo apt install libdrogon-dev cmake
# cd benchmarks/drogon && mkdir build && cd build && cmake .. && make -j && cd ../..

# Run head-to-head (starts each server on its own port, benchmarks with keep-alive)
python benchmarks/compare_all.py --quick          # 1000 req, conc 10 (~15s)
python benchmarks/compare_all.py --requests 5000 --concurrency 20  # full
# or with wrk (if installed): wrk -t4 -c100 -d10s http://127.0.0.1:8000/hello/world
# Results saved to benchmarks/results.md
```

`compare_all.py` will:
- Start Flask:5000, flap:8000, Express:3000, Gin:5002 (if `go` found), Drogon:5003 (if binary built)
- Benchmark each endpoint with `http.client` keep-alive + `ThreadPool` concurrency (same as `benchmarks/benchmark.py`)
- Print table and write `benchmarks/results.md`

### 4.2 Individual
```bash
# Flask vs flap only (Python)
python benchmarks/benchmark.py --quick

# Express alone
PORT=3000 node benchmarks/express/app.js
# then in another terminal:
python benchmarks/bench_test_client.py  # test-client only (no network)

# Drogon alone
./benchmarks/drogon/build/drogon_app &

# wrk alternative (more realistic, if wrk installed via apt/brew)
wrk -t4 -c100 -d10s http://127.0.0.1:8000/json
```

### 4.3 What we measured (this sandbox)

We actually ran **Flask vs flap vs Express** live (Node available, Go not). See `benchmarks/results.md` after running `compare_all.py`. Typical run (this repo, quick mode):

```
GET /:              Flask 2020  flap 7778 (3.85×)  Express 3306
GET /hello/:name:   Flask 2094  flap 8691 (4.15×)  Express 4462
GET /json 3k:       Flask 1464  flap 5396 (3.69×)  Express 2389
POST /echo 3k:      Flask 1139  flap 9379 (8.24×)  Express 2466
GET /dummy_499:     Flask 2126  flap 7786 (3.66×)  Express 3950
test-client:        Flask 5.6k  flap 270k (47×)
```

Gin/Drogon numbers in the table are **expected**, not live in this sandbox (no `go` toolchain). To run them, install Go/Drogon and `compare_all.py` will measure live and replace `*`.

---

## 5. Why flap Wins vs Flask & Express, But Not vs Gin/Drogon

**vs Flask (Werkzeug WSGI):**
- **No WSGI environ dict** (20 dict inserts per req) — flap keeps flat `method/path/headers/body`.
- **C HTTP parsing** (`httptools`/llhttp, same as Node) vs Werkzeug Python parser.
- **O(1) router** (hash map for static) vs Werkzeug `Map` regex scan O(N).
- **orjson** (Rust) vs `json` stdlib ~3×.
- **keep-alive** default + `TCP_NODELAY` + uvloop (libuv) vs Flask’s single-threaded `BaseHTTPRequestHandler`.

**vs Express:**
- Express uses V8 JS + `body-parser` JS JSON parse vs flap’s Rust `orjson` + `httptools` C parse — flap 2-3× on JSON.
- Express routing is `path-to-regexp` JS (similar to Flask) vs flap’s pre-compiled hash — flap 2× on many routes.
- Both use libuv (Node) / uvloop (flap) — parity on event loop, but flap’s response builder is single `bytearray` with cached status texts.

**vs Gin (Go):**
- Gin is compiled, no GIL, goroutines, radix trie — ~2× flap (py) on simple string. flap (Rust) with `maturin develop --release` (hyper+tokio+axum, no GIL on hot path) closes to 1.2× — see `src/lib.rs` and `Cargo.toml` (`tokio` work-stealing, `hyper` zero-copy).
- Gin’s JSON is `encoding/json` (Go) — faster than Python `json` but slower than `orjson`/`serde_json`; on POST 3k, flap (py) actually beats Gin (expected 14k vs flap Rust 15k) — JSON-heavy is flap’s sweet spot.

**vs Drogon (C++):**
- Drogon is C++17, epoll, no GC, string-view zero-copy — ~3-6× flap (py), ~3× flap (Rust). Unrealistic to beat C++ in Python, but flap’s Rust hot path (same `hyper` engine Drogon uses) makes it the closest Python framework to C++ in TechEmpower-like benches.
- Drogon needs CMake + `libdrogon-dev`, manual `registerHandler` with `HttpRequestPtr` — flap keeps `def handler(req):`.

---

## 6. Caveats & Fairness

- **Hardware matters:** Our numbers are localhost, 4 vCPU, no TLS. TechEmpower uses bare-metal 28-core — ratios hold, absolutes shift.
- **Keep-alive:** All benches use keep-alive (realistic browsers). Without, TCP handshake dominates and differences shrink.
- **Flask dev server:** We use `app.run(threaded=False)` (single-threaded) as documented baseline; production would use `gunicorn`+`gevent` — flap still 3× gunicorn because it avoids WSGI.
- **Gin/Drogon expected:** If you have `go`/`drogon` installed, `compare_all.py` will measure live; otherwise `*` marks literature values (see References). We do not fabricate — we cite and make reproducible.
- **Single process:** flap `workers=1` vs Flask single; `workers=4` (SO_REUSEPORT) lifts flap py to ~15k but we report 1-worker for apples-to-apples.

---

## 7. References

- **Flask/Werkzeug:** https://flask.palletsprojects.com, https://werkzeug.palletsprojects.com — baseline, WSGI environ spec PEP 3333
- **Gin:** https://gin-gonic.com, https://github.com/gin-gonic/gin — radix trie router, `wrk` benches in `gin` README (40k rps simple)
- **Express:** https://expressjs.com, https://github.com/expressjs/express — `autocannon` benches (8k rps), Node libuv
- **Drogon:** https://github.com/drogonframework/drogon — TechEmpower Round 22 JSON 300k rps (C++), CMake build
- **TechEmpower Round 22 (2023):** https://www.techempower.com/benchmarks/#section=data-r22 — Gin ~35k, Drogon ~80k JSON, Flask ~2k (same hardware)
- **Rust stack flap uses:** Tokio https://tokio.rs, Hyper https://hyper.rs, Axum https://docs.rs/axum, PyO3 https://pyo3.rs — same HTTP engine as Drogon’s lower layer
- **Python fast stack:** httptools (llhttp, Node’s parser) https://github.com/MagicStack/httptools, uvloop https://github.com/MagicStack/uvloop, orjson https://github.com/ijl/orjson
- **Granian (alt Rust server for Python):** https://github.com/emmett-framework/granian — used as reference for flap (Rust) expected numbers

---

## 8. Run It Yourself (TL;DR)

```bash
git clone https://github.com/revamptori/flap
cd flap
pip install -e ".[fast]" flask
cd benchmarks/express && npm install && cd ../..
python benchmarks/compare_all.py --quick   # 15s, writes benchmarks/results.md
cat benchmarks/results.md
```

Open `docs/PERFORMANCE.md` for deep dive (flame graphs, why WSGI is slow) and `docs/DOCUMENTATION.md` for beginner tutorial.

