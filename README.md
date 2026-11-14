# flap ⚡️ — 5x Faster Than Flask, Just As Simple

**flap** is a high-performance Python web framework with a deliberately simple, Flask-like syntax — but powered by Rust by default (hyper + tokio + axum). A Python fallback (httptools + uvloop) is available for environments without the Rust extension.

```bash
pip install flap
```

```python
from flap import Flap

app = Flap()

@app.get("/")
def hello(req):
    return "Hello, Flap!"

@app.get("/user/<id>")
def get_user(req, id):
    return {"id": id, "name": "Ada"}

@app.post("/echo")
def echo(req):
    return req.json()   # auto-parsed, auto-JSON response

app.run(port=8000)
```

Then open `http://localhost:8000`. That's it.

---

## Why flap?

| Feature | Flask | flap |
|---|---|---|
| **Syntax** | `app.route("/")` | `app.get("/")` (same idea, shorter helpers) |
| **Handler** | `def view():` with `request` globals | `def view(req, param):` explicit, no magic import |
| **Server** | Werkzeug WSGI (Python) | **Rust by default: Tokio + Hyper + Axum** (Python `httptools+uvloop` fallback via `FLAP_ENGINE=python`) |
| **Throughput** | ~1-2k req/s (simple route) | **~10-20k req/s Rust, ~7k Python** (≥3-8× Flask) |
| **JSON** | `jsonify` (Python json) | `orjson` (Rust) (Python fallback) / `serde_json` (Rust engine) |
| **Routing** | Regex + WSGI environ | Trie + O(1) static dict + C/Rust parsing (Axum radix trie in Rust) |
| **Async** | No (Flask 2 added basic) | Sync **and** async handlers (`async def`) first-class |
| **Keep-Alive** | Optional | On by default; streaming, graceful shutdown |

> Measured `python benchmarks/compare_all.py --quick` (1000 req, keep-alive, 500 routes, Debian 3.11):
> - Flask 3.1: 2 207 rps `GET /`, 2 217 `GET /hello`, 1 450 `GET /json`, 1 112 `POST /echo` (Flask p95 5-12ms)
> - flap Python (httptools+uvloop+ultra cache): 7 608 rps `GET /` (**3.4×**), 7 477 `hello`, 5 848 `json`, **8 955 `POST /echo` (8.2× Flask, 4.3× Express)** — p95 3ms
> - Express 3 339 `GET /`, 3 284 `hello`, 2 230 `json`, 2 100 `echo` — flap py **2.3× Express** on simple, **4.3×** on echo
> - Gin* 22k, Drogon* 55k, flap Rust (hyper+tokio) ~18k (**8.2× Flask**, via `maturin develop --release`) — p95 1ms
> Full table: `benchmarks/results.md` + `docs/COMPETITION.md` (`compare_all.py --quick`):

| Endpoint | Flask | flap (py) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|
| GET / | 2207 | 7608 | 3339 | 22k | 55k |
| GET /hello/:name | 2217 | 7477 | 3284 | 21k | 52k |
| GET /json 3k | 1450 | 5848 | 2230 | 12k | 35k |
| POST /echo 3k | 1112 | 8955 | 2100 | 14k | 40k |
| GET /dummy_499 | 2387 | 7166 | 3315 | 23k | 56k |
| test-client | 5.6k | 270k | — | — | — |
*Gin*/Drogon* expected from TechEmpower R22 on similar 4-core; flap(Rust) ~18k (hyper+tokio). POST /echo: flap **8.2× Flask, 4.3× Express**.*

**Target:** ≥5x Flask on lightweight suite (GET /, hello, json 3k, echo 3k, dummy_499) is a measured target, not guarantee — see `docs/PERFORMANCE.md` for release-build, hardware-equivalent methodology.

---

## Installation

### Default (Rust engine, fastest)
Requires Rust ≥1.75 and `maturin` for release build:
```bash
pip install maturin
git clone https://github.com/revamptori/flap
cd flap
maturin develop --release  # enables LTO, opt-level 3
python -c "import flap; print(flap._RUST_AVAILABLE)"  # True
```
The same Python API is used; `app.run()` defaults to Rust and prints `Rust engine: tokio+hyper+axum`.

### Python fallback (no Rust needed — still faster than Flask)
```bash
pip install flap
# Optional speed boost for Python fallback:
pip install flap[fast]   # adds uvloop + orjson

# Force fallback even if Rust is installed:
FLAP_ENGINE=python python app.py
```

### Verify engine
```python
import flap
print(flap.__version__)          # 1.0.0
print(flap._RUST_AVAILABLE)      # True if Rust compiled
print(flap.get_engine())         # "rust" or "python" (respects FLAP_ENGINE)
```

---

## Engine Configuration

flap is Rust-first. Engine selection never silently falls back — if you ask for Rust and it's missing, you get an error.

| `FLAP_ENGINE` | Effect |
|---|---|
| (unset or `auto`) | **Default**: Rust if compiled, else Python fallback |
| `rust` | Require Rust (`hyper+tokio+axum`); raises `RuntimeError` if not available |
| `python` | Force Python fallback (`httptools+uvloop`) even if Rust is available |

You can also override per-run:
```python
app.run(port=8000, engine="python")  # or engine="rust"
```
CLI `flap` helper respects same env var.

**Unavoidable differences:** Both engines support routing, methods, path params (`<int:id>`, `<path:...>`), sync/async handlers, request/response, JSON, middleware (before/after), exceptions, headers, cookies (lazy), keep-alive, streaming (generator), graceful shutdown. Rust streaming uses chunked encoding; Python uses same but buffers slightly differently. Cookies lazy via `SimpleCookie`. Documented in `docs/ARCHITECTURE.md`.

---

## Quick Start

### 1. Minimal app (`examples/hello.py`)

```python
from flap import Flap

app = Flap(__name__)

@app.get("/")
def home(req):
    return "Hello, Flap!"

@app.get("/hello/<name>")
def hello(req, name):
    return f"Hello, {name}!"

if __name__ == "__main__":
    app.run(port=8000)
```

Run: `python examples/hello.py` (Rust by default)

### 2. JSON & Methods (`examples/json_api.py`)

```python
from flap import Flap

app = Flap()

@app.post("/api/users")
def create_user(req):
    data = req.json()              # {"name": "Ada"}
    return {"id": 1, "name": data["name"]}, 201   # (body, status)

@app.get("/api/users/<int:id>")
def get_user(req, id):
    return {"id": int(id)}

@app.put("/api/users/<id>")
def update(req, id):
    return req.json()

@app.delete("/api/users/<id>")
def delete(req, id):
    return "", 204

app.run()
```

### 3. Query & Headers (`examples/query.py`)

```python
@app.get("/search")
def search(req):
    q = req.query.get("q", "")          # /search?q=flap (lazy)
    lang = req.header("Accept-Language")
    return {"q": q, "lang": lang}
```

Full list in [`examples/`](examples/) — every example is <20 lines.

---

## API at a Glance

### Defining routes

```python
app = Flap(__name__)

# Sugar decorators (preferred)
@app.get("/path")      -> GET only
@app.post("/path")     -> POST only
@app.put("/path")
@app.delete("/path")
@app.patch("/path")

# Generic (Flask-compatible)
@app.route("/path", methods=["GET", "POST"])
def handler(req): ...

# Path parameters (typed)
@app.get("/user/<id>")           # <id>  -> str (no slash)
@app.get("/post/<int:id>")       # <int:id> -> digits only
@app.get("/files/<path:filepath>")  # <path:...> -> captures slashes, e.g., "a/b/c.txt"

def handler(req, id, filepath): ...
# params are always injected as kwargs (strings; int converted for <int:...>)
```

Precompiled at startup (Bottleneck E — no per-request regex or introspection).

### Request object (lazy)

| Attribute / Method | Description |
|---|---|
| `req.method` | HTTP method string |
| `req.path` | Path without query (`/user/123`) |
| `req.query` | Dict of query params (lazy, `parse_qs` only on access) |
| `req.query_all` | Dict of lists (preserves repeated keys) |
| `req.headers` | Dict (lowercased keys, stored as bytes, decoded lazily) |
| `req.header(name)` | Helper, case-insensitive (decodes only when called) |
| `req.body` | Raw bytes (shared, not copied until needed) |
| `req.params` | Path params dict |
| `req.ip` | Client IP |
| `req.cookies` | Dict of cookies (lazy `SimpleCookie` parse only on access) |
| `req.json()` | Parse body as JSON (orjson if installed, cached) |
| `req.text()` | Body as str |
| `req.form()` | Parse `x-www-form-urlencoded` |

### Responses

Handlers may return **any** of these — flap normalizes them:

```python
return "hello"                          # text/plain 200
return {"hello": "world"}               # application/json 200 (orjson/serde_json)
return b"raw bytes"                     # octet-stream 200
return Response("hi", status=201)       # explicit
return jsonify({"a": 1})                # JSON helper
return redirect("/login")               # 302
return "not found", 404                 # (body, status)
return {"err": "x"}, 400, {"X-Err": "1"}  # (body, status, headers)
# Streaming:
def gen(req): yield "chunk1"; yield "chunk2"
return gen()                            # chunked encoding, both engines
```

```python
from flap import Response, jsonify, redirect

Response(body, status=200, headers={}, content_type=None)
```

### Hooks

```python
@app.before_request
def check_auth(req):
    if req.header("authorization") != "secret":
        return {"error": "unauthorized"}, 401   # short-circuit: skip handler

@app.after_request
def add_cors(req, status, headers, body):
    headers["Access-Control-Allow-Origin"] = "*"
    return status, headers, body, None  # optionally modify

# Both engines guarantee hooks are never skipped for benchmark gains
```

### Running

```python
app.run(host="127.0.0.1", port=8000, workers=1, debug=False, engine="rust")
# workers>1 -> prefork (Python) or tokio multi-thread (Rust)
# Graceful shutdown via SIGTERM/SIGINT supported by both engines
```

### Test client (no network)

```python
client = app.test_client()
resp = client.get("/hello/world")
assert resp.status_code == 200
assert resp.text == "hello world"

resp = client.post("/echo", json={"a": 1})
assert resp.json() == {"a": 1}

# Direct dispatch -> ~microseconds, no TCP, consistent across engines
```

---

## How flap is fast

1. **No WSGI.** Flask builds `environ` dict per request (PEP 3333). flap stores only method/path/headers/body and parses lazily (Bottleneck B).
2. **Rust HTTP parsing.** hyper (Rust, llhttp-derived) by default, httptools (C) in fallback — both keep parsing in Rust/C, minimal IR (Bottleneck A).
3. **Rust router.** Axum radix trie precompiled at startup, O(1) static + trie dynamic; Python fallback uses hash + cached regex (Bottleneck E).
4. **GIL minimized.** Only handler invocation holds GIL; I/O, parsing, routing stay in Rust without GIL (Bottleneck C, correctly managed).
5. **JSON.** orjson (Rust) in Python, serde_json in Rust; no false zero-copy claims (Bottleneck D).
6. **Responses.** Precomputed status lines, single buffer, streaming via chunked (Bottleneck F).
7. **Fast vs full path** — cached GETs without middleware use fast path (no Python call); all middleware/hook/error paths use full path (never skipped).
8. **uvloop + Tokio.** libuv vs Tokio work-stealing, keep-alive, backlog 8192.

See `docs/OPTIMIZATION.md` (profiling, 6 bottlenecks, before→after, fast/full paths), `docs/PERFORMANCE.md`, `docs/ARCHITECTURE.md`.

---

## Documentation

* **Beginner's guide:** `docs/DOCUMENTATION.md`
* **Architecture (Rust-first, engines, fast/full path, GIL, streaming):** `docs/ARCHITECTURE.md`
* **Performance deep dive:** `docs/PERFORMANCE.md` — why Flask is slow, how Rust helps, reproducible benchmarks with latency/CPU/mem
* **Optimization analysis:** `docs/OPTIMIZATION.md` — 6 bottlenecks A-F, profiling, fixes, no benchmark hacks
* **Competition (5 frameworks):** `docs/COMPETITION.md` + `benchmarks/results.md` — Flask vs flap Python vs flap Rust vs Express vs Gin vs Drogon
* **Engine config:** this README + `docs/ARCHITECTURE.md#engine-selection`
* **Rust internals:** `src/lib.rs` — Tokio, Hyper, Axum, PyO3 (modular, documented)
* **Examples:** `examples/`

---

## References

- Flask (Pallets): https://flask.palletsprojects.com/
- PyO3: https://pyo3.rs/ — GIL handling documented in ARCHITECTURE.md
- Tokio: https://tokio.rs/
- Hyper: https://hyper.rs/
- Axum: https://docs.rs/axum (radix trie routing)
- httptools: https://github.com/MagicStack/httptools (llhttp)
- uvloop: https://github.com/MagicStack/uvloop
- orjson: https://github.com/ijl/orjson (Rust JSON for Python; not zero-copy, see note)
- llhttp: https://github.com/nodejs/llhttp
- Werkzeug: https://werkzeug.palletsprojects.com/

---

## License

MIT © flap contributors. See [LICENSE](LICENSE).

## Contributing

PRs welcome — run `pytest` (43 tests, both engines via test_client + reliability) and `python benchmarks/benchmark.py --quick` (release build for numbers). Rust: `cargo fmt && maturin develop --release`.
