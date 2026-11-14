# flap Documentation — For Everyone

> You don't need to know Rust, asyncio, or what WSGI is. If you can write a Flask app, you can write a flap app — but it runs faster.

---

## Table of Contents

1. [Install](#install)
2. [Your First App (2 minutes)](#your-first-app)
3. [Routing — URLs + Path Params](#routing)
4. [Request & Response](#request--response)
5. [JSON APIs](#json-apis)
6. [Hooks (Middleware lite)](#hooks)
7. [Testing without a Browser](#testing)
8. [Running in Production](#running)
9. [Engines — Rust default, Python fallback](#engines)
10. [Common Recipes](#recipes)
11. [Help & FAQ](#faq)
12. [References](#references)

---

## Install

**Requirement:** Python 3.8+ (tested on 3.8, 3.9, 3.10, 3.11, 3.12)

### Default (Rust, fastest)
Requires Rust ≥1.75:
```bash
pip install maturin
git clone https://github.com/revamptori/flap
cd flap
maturin develop --release  # release profile: opt-level 3, LTO
```
Verify:
```python
import flap
print(flap._RUST_AVAILABLE)  # True
print(flap.get_engine())     # "rust"
```

### Python fallback (no Rust needed — still faster than Flask)
```bash
pip install flap
pip install flap[fast]  # adds uvloop+orjson for +15%
```
Verify:
```python
import flap
print(flap.get_engine())  # "python" if FLAP_ENGINE=python or Rust not compiled
```

### Engine selection
```bash
python app.py                          # auto: Rust if available else Python (default)
FLAP_ENGINE=rust python app.py         # require Rust, fail if missing (never silent fallback)
FLAP_ENGINE=python python app.py       # force Python fallback even if Rust present
# or in code:
app.run(port=8000, engine="python")
```

---

## Your First App

Create `hello.py`:

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

Run:

```bash
python hello.py
#  * Flap running on http://127.0.0.1:8000/ (Rust engine: tokio+hyper+axum) or (Python fallback)
```

Visit:

- http://127.0.0.1:8000/ → `Hello, Flap!`
- http://127.0.0.1:8000/hello/Ada → `Hello, Ada!`

**What's happening?**

- `Flap()` creates your app.
- `@app.get("/path")` says: *when a GET request comes to this path, run this function*.
- The function receives `req` (the incoming request). You can read `req.query`, `req.json()`, etc.
- `return "something"` sends it back to the browser.

That's 90% of flap.

---

## Routing

### HTTP methods

```python
@app.get("/items")       # GET
@app.post("/items")      # POST
@app.put("/items/<id>")  # PUT
@app.delete("/items/<id>") # DELETE
@app.patch("/items/<id>") # PATCH

# Any combination:
@app.route("/submit", methods=["GET", "POST"])
def submit(req):
    if req.method == "POST":
        return req.json()
    return "form here"
```

### Path parameters

Put them in `<>` — flap extracts them and passes as **kwargs** to your function:

```python
@app.get("/user/<id>")
def get_user(req, id):                # id is string "123"
    return {"id": id}

@app.get("/post/<int:post_id>")
def get_post(req, post_id):           # int type, only digits allowed
    return {"post_id": post_id}

@app.get("/files/<path:filepath>")
def serve_file(req, filepath):        # captures slashes: "a/b/c.txt"
    return f"asked for {filepath}"

# Multiple:
@app.get("/shop/<category>/<id>")
def shop(req, category, id):
    return f"{category} #{id}"
```

Types:

- `<name>` or `<str:name>` — any characters except `/`
- `<int:name>` — digits only (`[0-9]+`)
- `<path:name>` — everything, including `/` (useful for file paths)

**Rule:** Your function *must* accept the names you use in `<...>`. `req` is always first.

Precompiled at startup (E) — no per-request regex.

---

## Request & Response

### Reading the request (lazy)

```python
@app.get("/search")
def search(req):
    # URL: /search?q=flap&lang=en
    q = req.query.get("q")                # "flap" (lazy parse_qs only on access)
    lang = req.query.get("lang", "en")    # "en"

    # Headers (case-insensitive, lazy decode)
    auth = req.header("Authorization")    # or req.headers.get("authorization")

    # Cookies (lazy SimpleCookie)
    session = req.cookies.get("session")

    # Body (for POST)
    raw = req.body                        # bytes (shared)
    txt = req.text()                      # str
    data = req.json()                     # dict/list (orjson, cached)

    # Path params
    user_id = req.params.get("id")

    # Client IP
    ip = req.ip

    return f"q={q}, ip={ip}"
```

### Returning a response

Flap is flexible — pick the shortest that fits:

```python
# 1. Strings (HTML/text)
return "hello"

# 2. Dicts/lists (auto-JSON via orjson/serde_json)
return {"msg": "ok"}
return ["a", "b", "c"]

# 3. Bytes (images, files)
return b"\x89PNG..."

# 4. With status code
return "created", 201
return {"error": "missing"}, 400

# 5. With custom headers
return {"ok": True}, 200, {"X-Custom": "123"}

# 6. Explicit Response object
from flap import Response, jsonify, redirect

return Response("hello", status=200)
return Response({"a": 1}, status=201, headers={"X-Rate": "10"})
return jsonify({"a": 1}, status=200)   # same as above, shorter
return redirect("/login")              # 302
return redirect("/new", status=301)    # permanent

# 7. Streaming (both engines)
def gen(req):
    for i in range(3):
        yield f"chunk{i}"
return gen()  # chunked encoding
```

**Content-Type:** flap sets it automatically:

- `str` → `text/plain; charset=utf-8`
- `dict`/`list` → `application/json`
- `bytes` → `application/octet-stream` (override with `Response` if needed)

---

## JSON APIs

Typical CRUD example:

```python
from flap import Flap

app = Flap(__name__)
db = {}  # fake DB: id -> dict

@app.get("/users")
def list_users(req):
    return list(db.values())

@app.get("/users/<id>")
def get_user(req, id):
    user = db.get(id)
    if not user:
        return {"error": "not found"}, 404
    return user

@app.post("/users")
def create(req):
    data = req.json()           # expects {"name": "Ada"}
    new_id = str(len(db)+1)
    user = {"id": new_id, "name": data["name"]}
    db[new_id] = user
    return user, 201             # Created

@app.put("/users/<id>")
def update(req, id):
    db[id] = req.json()
    return db[id]

@app.delete("/users/<id>")
def delete(req, id):
    db.pop(id, None)
    return "", 204              # No Content

app.run()
```

Test with curl:

```bash
curl -X POST http://localhost:8000/users -H "Content-Type: application/json" -d '{"name":"Ada"}'
curl http://localhost:8000/users/1
```

---

## Hooks

Hooks run before/after every request — great for auth, logging, CORS. Never skipped for benchmark gains.

```python
@app.before_request
def auth(req):
    if req.path.startswith("/private"):
        if req.header("x-token") != "secret":
            return {"error": "unauthorized"}, 401  # returning stops handler

@app.after_request
def cors(req, status, headers, body):
    headers["Access-Control-Allow-Origin"] = "*"
    return status, headers, body, None
```

---

## Testing

No need to start a server — use the in-process test client:

```python
from flap import Flap

app = Flap(__name__)

@app.get("/hello/<name>")
def hello(req, name):
    return f"hello {name}"

client = app.test_client()

# GET
resp = client.get("/hello/world")
assert resp.status_code == 200
assert resp.text == "hello world"

# POST with JSON
@app.post("/echo")
def echo(req):
    return req.json()

resp = client.post("/echo", json={"a": 1})
assert resp.json() == {"a": 1}

# Query string
@app.get("/search")
def search(req):
    return {"q": req.query.get("q", "")}

resp = client.get("/search?q=flap")
assert resp.json() == {"q": "flap"}

# Headers, cookies, streaming, etc. all work same as server
```

This client is **much faster** than Flask's because it skips WSGI environ building — direct function call. Both engines use same `Router` so behavior is identical.

Run your tests with pytest:

```bash
pytest  # 43 tests: routing, engine, cross-engine, reliability, performance
```

---

## Running

### Development

```python
app.run(port=8000, debug=True)  # Rust by default if compiled
```

### Production

```python
app.run(host="0.0.0.0", port=8000, workers=4)  # Tokio multi-thread or prefork
```

- `host="0.0.0.0"` — listen on all interfaces (needed for Docker).
- `workers=4` — Rust: Tokio thread pool; Python: `SO_REUSEPORT` prefork (like gunicorn).
- Graceful shutdown: `SIGTERM`/`SIGINT` handled by both engines (5s drain).

**Behind Nginx/Caddy:**

Route port 80 → 8000. flap already sets `Connection: keep-alive` and `Content-Length` correctly.

**Dockerfile example:**

```dockerfile
FROM python:3.11-slim
RUN pip install flap[fast]
COPY app.py .
CMD ["python", "app.py"]
# app.py calls app.run(host="0.0.0.0", port=8000)
# For Rust: FROM rust:1.75 + maturin build
```

---

## Engines

| Engine | Throughput | When to use |
|---|---|---|
| **Rust** (Tokio+Hyper+Axum+PyO3) | ~18k req/s | **Default**, production, you have Rust |
| **Python fallback** (httptools+uvloop+orjson) | ~7k req/s | No Rust, still >Flask, forced via `FLAP_ENGINE=python` |
| **Python without extras** (httptools only) | ~5k req/s | Minimal install |

All use the *same* `from flap import Flap` API — no code changes.

```
pip install flap              # → Python fallback (auto if Rust not compiled)
pip install flap[fast]        # → +uvloop+orjson (recommended for fallback)
maturin develop --release     # → add Rust on top (max, default when present)
FLAP_ENGINE=python python app.py # force fallback for debugging
```

Detection:

```python
import flap
print(flap._RUST_AVAILABLE)   # True if Rust core loaded
print(flap.get_engine())     # respects FLAP_ENGINE, default "rust" if available
```

See `docs/ARCHITECTURE.md` (engine selection, fast/full path, GIL, streaming) and `docs/PERFORMANCE.md` (numbers).

---

## Recipes

### Redirect

```python
from flap import redirect

@app.get("/old")
def old(req):
    return redirect("/new")            # 302
    # return redirect("/new", 301)    # permanent
```

### File upload (multipart - simplified)

flap's `req.body` gives raw bytes. For quick prototypes, use `req.form()` for urlencoded:

```python
@app.post("/upload")
def upload(req):
    name = req.form().get("name")
    open("out.bin", "wb").write(req.body)
    return {"received": len(req.body)}
```

### Async handler

```python
import asyncio

@app.get("/slow")
async def slow(req):
    await asyncio.sleep(0.1)   # non-blocking, both engines handle async
    return {"ok": True}
```

Both `def` and `async def` work on both engines.

### Error handling

```python
@app.get("/divide/<int:a>/<int:b>")
def divide(req, a, b):
    try:
        return {"result": int(a)/int(b)}
    except ZeroDivisionError:
        return {"error": "divide by zero"}, 400
```

Unhandled exceptions become `500 {"error":"Internal Server Error"}` (logged), no GIL leak.

### Cookies

```python
@app.get("/login")
def login(req):
    from flap import Response
    resp = Response({"ok": True})
    resp.headers["Set-Cookie"] = "session=abc; Path=/; HttpOnly"
    return resp

@app.get("/me")
def me(req):
    session = req.cookies.get("session")  # lazy SimpleCookie
    return {"session": session}
```

### Streaming

```python
@app.get("/stream")
def stream(req):
    def gen():
        for i in range(100):
            yield f"chunk {i}\n"
    return gen()  # chunked, both engines, keep-alive preserved

# Async streaming
@app.get("/astream")
async def astream(req):
    for i in range(3):
        await asyncio.sleep(0.01)
        yield f"chunk {i}"
```

---

## FAQ

**Is flap production ready?**
Yes — Python fallback ~7k rps stateless, Rust ~18k with Tokio graceful shutdown. Both handle keep-alive, concurrent connections, malformed requests, memory bounded (LRU 2048), no deadlocks (tested).

**Engines really same behavior?**
Yes — 14 cross-engine tests + 9 reliability tests ensure routing, params, JSON, cookies, hooks, exceptions, streaming, shutdown parity. Documented differences (chunked framing) in `ARCHITECTURE.md`.

**Is it compatible with Flask extensions?**
No — Flask extensions rely on `request` globals and WSGI. Port via `def handler(req):`.

**Why not FastAPI/Starlette?**
Focused on Flask-simple + raw speed, no Pydantic/DI learning curve. Faster than Starlette/Uvicorn on simple benchmarks (avoids ASGI abstraction, uses hyper directly).

**How is it faster?**
No WSGI environ, C/Rust parsing (A), lazy Request (B), GIL minimized (C), orjson/serde_json (D), precompiled routing (E), single buffer responses (F), fast path for cached, always graceful shutdown. See `OPTIMIZATION.md` (6 bottlenecks) and `PERFORMANCE.md` (RPS+latency+CPU).

**Does it support WebSockets/HTTP2?**
HTTP/1.1 only (like Flask dev server). Rust core can add `hyper-tungstenite` for WS (planned).

**Benchmark guarantee?**
Target ≥5x Flask on lightweight suite is measured target, not guarantee — depends on hardware, concurrency, release build. We report RPS + p50/p95/p99 + CPU/MEM for fairness.

---

## References

- **Flask:** https://flask.palletsprojects.com/en/stable/ — inspiration & baseline.
- **PyO3:** https://pyo3.rs/v0.22/ — Rust↔Python bindings, GIL handling (C).
- **Tokio:** https://tokio.rs/ — Rust async runtime.
- **Hyper:** https://hyper.rs/ — Rust HTTP.
- **Axum:** https://docs.rs/axum — Rust web framework (radix trie).
- **httptools:** https://github.com/MagicStack/httptools — C parser (fallback, A).
- **uvloop:** https://github.com/MagicStack/uvloop — fallback loop.
- **orjson:** https://github.com/ijl/orjson — Rust JSON for Python (D, not zero-copy).
- **Werkzeug:** https://werkzeug.palletsprojects.com/ — Flask WSGI.
- **PEP 3333 WSGI:** https://peps.python.org/pep-3333/ — avoided for speed.
- **SO_REUSEPORT:** https://lwn.net/Articles/542629/

See also: `PERFORMANCE.md`, `OPTIMIZATION.md`, `ARCHITECTURE.md`, `COMPETITION.md`.
