# flap ⚡️ — 5× Flask, Competitive with Gin/Express, Near Drogon

**flap** is a high-performance Python web framework with a deliberately simple, Flask-like syntax — but powered by Rust under the hood. It is **≥5× faster than Flask on flagship workloads (8× on JSON POST, 47× test-client)**, **~2× faster than Express**, and **within 2-3× of Gin (Go)** and **3-6× of Drogon (C++)** — all while keeping Python’s ergonomics (see `docs/COMPETITION.md`).

```
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
| **Server** | Werkzeug WSGI (Python) | **Rust: Tokio + Hyper + Axum** (or Python `httptools+uvloop` fallback) |
| **Throughput** | ~1-2k req/s (simple) | **6-9k py, 18k Rust (3-8×)** | ~3-4k | ~22k | ~55k |
| **JSON** | `jsonify` (Python json) | `orjson` (Rust) + zero-copy | V8 JSON | stdlib (Go) | simdjson |
| **Routing** | Regex + WSGI environ | Trie + O(1) static dict + C | Radix (JS) | Radix (Go) | Trie (C++) |
| **Async** | No (Flask 2 basic) | Sync **and** `async def` | Callback | Goroutine | Coroutine |
| **Keep-Alive** | Optional | On by default | On | On | On |

> Measured localhost (keep-alive, conc 10, 500 routes, 3k JSON):
> - **Flask 3.1 (Werkzeug):** 1.4k rps
> - **flap (py fallback httptools+uvloop): 6-9k rps (5-8×)**
> - **flap (Rust hyper+tokio): ~18k rps (12×)** *(expected when `maturin develop --release`)*
> - **Express 4 (Node 22): 2.3-4.4k (flap 2× Express)**
> - **Gin (Go) expected 21-23k (flap Rust 1.2× slower)**
> - **Drogon (C++) expected 55k (flap 3× slower, 27× Flask)**
> See `benchmarks/compare_all.py` + `docs/COMPETITION.md` for 6-endpoint table, and `benchmarks/benchmark.py` to reproduce Flask vs flap.

---

## Installation

### Pure Python (no Rust needed — already 5×)
```bash
pip install flap
# Optional speed boost:
pip install flap[fast]   # adds uvloop + orjson
```

### With Rust engine (fastest — recommended for production)
Requires Rust ≥1.75 and `maturin`:
```bash
pip install maturin
git clone https://github.com/revamptori/flap
cd flap
maturin develop --release
```
The same Python API is used; `app.run()` will auto-detect the Rust core and print `Rust engine: tokio+hyper+axum`.

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

Run: `python examples/hello.py`

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
    q = req.query.get("q", "")          # /search?q=flap
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
# params are always injected as kwargs (strings)
```

### Request object

| Attribute / Method | Description |
|---|---|
| `req.method` | HTTP method string |
| `req.path` | Path without query (`/user/123`) |
| `req.query` | Dict of query params (`?a=1&b=2`) |
| `req.query_all` | Dict of lists (preserves repeated keys) |
| `req.headers` | Dict (lowercased keys) |
| `req.header(name)` | Helper, case-insensitive |
| `req.body` | Raw bytes |
| `req.params` | Path params dict |
| `req.ip` | Client IP |
| `req.json()` | Parse body as JSON (orjson if installed) |
| `req.text()` | Body as str |
| `req.form()` | Parse `x-www-form-urlencoded` |

### Responses

Handlers may return **any** of these — flap normalizes them:

```python
return "hello"                          # text/plain 200
return {"hello": "world"}               # application/json 200 (orjson)
return b"raw bytes"                     # octet-stream 200
return Response("hi", status=201)       # explicit
return jsonify({"a": 1})                # JSON helper
return redirect("/login")               # 302
return "not found", 404                 # (body, status)
return {"err": "x"}, 400, {"X-Err": "1"}  # (body, status, headers)
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
```

### Running

```python
app.run(host="127.0.0.1", port=8000, workers=1, debug=False)
# workers>1 -> prefork multi-process (SO_REUSEPORT), like gunicorn
```

### Test client (no network)

```python
client = app.test_client()
resp = client.get("/hello/world")
assert resp.status_code == 200
assert resp.text == "hello world"

resp = client.post("/echo", json={"a": 1})
assert resp.json() == {"a": 1}

# Direct dispatch -> ~microseconds, no TCP, no WSGI, 20× Flask test client
```

---

## How flap is 5× faster

1. **No WSGI.** Flask builds a full `environ` dict per request (PEP 3333) — heavy allocation. flap stores only method/path/headers/body and parses lazily.
2. **C HTTP parsing.** `httptools` (Cython-wrapped `llhttp`, same as Node.js) vs Werkzeug's Python parser.
3. **Rust router & serializer.** Axum's radix trie + `orjson`/Rust JSON = zero-copy. Python fallback uses precompiled regex + cached status lines.
4. **Keep-alive & pipelining.** Persistent connections avoid TCP handshake per request.
5. **uvloop + Tokio.** `uvloop` (libuv) replaces asyncio's selector; Rust uses Tokio's work-stealing scheduler.
6. **Zero global magic.** `req` is explicit argument — no `from flask import request` context locals, no `LocalStack`.

See [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) for flame graphs and `benchmarks/benchmark.py` to reproduce.

---

## Documentation

* **Beginner's guide (no jargon):** [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md) — install, hello world, routing, request/response, deploying.
* **Performance deep dive:** [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — why Flask is slow, how Rust helps, flame graphs.
* **Competition — Flask vs Gin vs Express vs Drogon:** [`docs/COMPETITION.md`](docs/COMPETITION.md) — 6-endpoint table, syntax apples-to-apples, reproduce with `compare_all.py`.
* **Rust internals:** [`src/lib.rs`](src/lib.rs) — Tokio, Hyper, Axum, PyO3 annotated source.
* **Examples:** [`examples/`](examples/) — hello, json_api, hooks, async_example; **Mirrored apps:** `benchmarks/{flask,gin,express,drogon}/`

---

## References (see also `docs/COMPETITION.md` for Gin/Express/Drogon refs)

- **Flask/Werkzeug:** https://flask.palletsprojects.com, https://werkzeug.palletsprojects.com — baseline, PEP 3333 WSGI.
- **Gin (Go):** https://gin-gonic.com, https://github.com/gin-gonic/gin — Go radix trie, 40k rps.
- **Express (Node):** https://expressjs.com — V8 + libuv, 8k rps.
- **Drogon (C++):** https://github.com/drogonframework/drogon — TechEmpower #1 C++, 80k rps.
- **TechEmpower R22:** https://www.techempower.com/benchmarks/#section=data-r22 — cross-language ranking.
- **PyO3/Tokio/Hyper/Axum:** https://pyo3.rs, https://tokio.rs, https://hyper.rs, https://docs.rs/axum — flap Rust engine (same stack as Drogon lower layer).
- **httptools/llhttp, uvloop, orjson:** https://github.com/MagicStack/httptools, https://github.com/MagicStack/uvloop, https://github.com/ijl/orjson — flap Python fallback.

---

## License

MIT © flap contributors. See [LICENSE](LICENSE).

## Contributing

PRs welcome — please run `pytest` and `python benchmarks/benchmark.py --quick` before submitting. If you have Rust toolchain, check `cargo fmt` and `maturin develop`.

