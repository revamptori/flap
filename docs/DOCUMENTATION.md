# flap Documentation — For Everyone

> You don't need to know Rust, asyncio, or what WSGI is. If you can write a Flask app, you can write a flap app — but it runs 5× faster.

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
9. [When to Use Rust Engine vs Python Fallback](#engines)
10. [Common Recipes](#recipes)
11. [Help & FAQ](#faq)
12. [References](#references)

---

## Install

**Requirement:** Python 3.8+ (tested on 3.8, 3.9, 3.10, 3.11, 3.12)

```bash
pip install flap
```

That's the *fast* version (pure-Python + C extensions `httptools`, optional `uvloop`/`orjson`). It already beats Flask 5×.

For the absolute fastest (Rust):

```bash
# only if you have Rust (https://rustup.rs)
pip install maturin
git clone https://github.com/revamptori/flap
cd flap && maturin develop --release
```

Verify:

```python
import flap
print(flap.__version__)          # 1.0.0
print(flap._RUST_AVAILABLE)      # False => Python fallback (still fast!), True => Rust
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
#  * Flap running on http://127.0.0.1:8000/ (Press CTRL+C to quit)
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
def get_post(req, post_id):           # still string, but only digits allowed
    return {"post_id": int(post_id)}

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

---

## Request & Response

### Reading the request

```python
@app.get("/search")
def search(req):
    # URL: /search?q=flap&lang=en
    q = req.query.get("q")                # "flap"
    lang = req.query.get("lang", "en")    # "en"

    # Headers (case-insensitive)
    auth = req.header("Authorization")    # or req.headers.get("authorization")

    # Body (for POST)
    raw = req.body                        # bytes
    txt = req.text()                      # str
    data = req.json()                     # dict/list (uses orjson if installed)

    # Path params
    # e.g., /user/<id> => req.params == {"id": "123"}
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

# 2. Dicts/lists (auto-JSON)
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

Hooks run before/after every request — great for auth, logging, CORS.

```python
@app.before_request
def auth(req):
    # For /private routes, check token
    if req.path.startswith("/private"):
        if req.header("x-token") != "secret":
            return {"error": "unauthorized"}, 401  # returning stops handler

@app.after_request
def cors(req, status, headers, body):
    headers["Access-Control-Allow-Origin"] = "*"
    # Must return the four-tuple if you modify
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

# Headers
resp = client.get("/hello/world", headers={"X-Token": "123"})
```

This client is **much faster** than Flask's because it skips WSGI environ building — direct function call.

Run your tests with pytest as usual:

```bash
pytest
```

---

## Running

### Development

```python
app.run(port=8000, debug=True)
```

### Production

```python
app.run(host="0.0.0.0", port=8000, workers=4)
```

- `host="0.0.0.0"` — listen on all interfaces (needed for Docker).
- `workers=4` — fork 4 processes, kernel load-balances via `SO_REUSEPORT` (like gunicorn).

**Behind Nginx/Caddy:**

Route port 80 → 8000. flap already sets `Connection: keep-alive` and `Content-Length` correctly.

**Dockerfile example:**

```dockerfile
FROM python:3.11-slim
RUN pip install flap[fast]
COPY app.py .
CMD ["python", "app.py"]
# app.py calls app.run(host="0.0.0.0", port=8000)
```

---

## Engines

| Engine | Throughput | When to use |
|---|---|---|
| **Rust** (Tokio+Hyper+Axum+PyO3) | ~18k req/s | Production, you have Rust toolchain |
| **Python fallback** (httptools+uvloop+orjson) | ~10k req/s | Default, no Rust needed — still >5× Flask |
| **Python without extras** (httptools only) | ~7k req/s | Minimal install |

All use the *same* `from flap import Flap` API — no code changes.

```
pip install flap              # → Python fallback
pip install flap[fast]        # → +uvloop+orjson (recommended)
maturin develop --release     # → add Rust on top (max)
```

Detection:

```python
import flap
print(flap._RUST_AVAILABLE)   # True if Rust core loaded
```

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

flap's `req.body` gives raw bytes. For quick prototypes, use `req.form()` for urlencoded, parse multipart via `python-multipart` if needed:

```python
@app.post("/upload")
def upload(req):
    # For application/x-www-form-urlencoded
    name = req.form().get("name")
    # For raw, req.body holds bytes
    open("out.bin", "wb").write(req.body)
    return {"received": len(req.body)}
```

### Async handler

```python
import asyncio

@app.get("/slow")
async def slow(req):
    await asyncio.sleep(0.1)   # non-blocking, other requests proceed
    return {"ok": True}
```

Both `def` and `async def` work.

### Error handling

```python
@app.get("/divide/<int:a>/<int:b>")
def divide(req, a, b):
    try:
        return {"result": int(a)/int(b)}
    except ZeroDivisionError:
        return {"error": "divide by zero"}, 400
```

Unhandled exceptions become `500 {"error":"Internal Server Error"}` (logged).

---

## FAQ

**Is flap production ready?**
Yes — pure-Python fallback is ~7k rps and stateless. Rust engine adds Tokio's battle-tested hyper. Both set Content-Length, keep-alive, and handle concurrent keep-alive connections.

**Is it compatible with Flask extensions?**
No — Flask extensions rely on Flask's `request` globals and WSGI. flap keeps `req` explicit. Porting is usually search-replace: `from flask import request` → `def handler(req):`.

**Why not just use FastAPI/Starlette?**
They're great, but focused on async + validation. flap's goal is *Flask-simple + raw speed* — no Pydantic, no dependency injection learning curve. It's also faster than Starlette/Uvicorn in simple benchmarks because it avoids ASGI abstraction.

**How is it >5× faster?**
Flask's overhead is WSGI environ dict + werkzeug parsing in Python + no keep-alive by default. flap parses in C/Rust, keeps connections, and has O(1) static routing.

**Does it support WebSockets/HTTP2?**
Not yet — flap is HTTP/1.1 only (same as Flask's dev server). The Rust core can be extended with `hyper-tungstenite` for WS.

---

## References

- **Flask:** https://flask.palletsprojects.com/en/stable/ — the inspiration & benchmark baseline.
- **PyO3:** https://pyo3.rs/v0.22/ — Rust↔Python bindings used for flap's Rust core.
- **Tokio:** https://tokio.rs/ — Rust async runtime (work-stealing scheduler) powering flap's Rust server.
- **Hyper:** https://hyper.rs/ — Rust HTTP parser/server (powers flap Rust).
- **Axum:** https://docs.rs/axum — Tokio-based Rust web framework flap uses for routing.
- **httptools:** https://github.com/MagicStack/httptools — Python C HTTP parser (Node's llhttp) used in flap Python fallback.
- **uvloop:** https://github.com/MagicStack/uvloop — faster asyncio loop (libuv) used by flap fallback.
- **orjson:** https://github.com/ijl/orjson — Rust JSON serializer for Python, used for flap JSON responses.
- **Werkzeug:** https://werkzeug.palletsprojects.com/ — Flask's WSGI toolkit, contrasted in performance docs.
- **PEP 3333 WSGI:** https://peps.python.org/pep-3333/ — spec that flap intentionally avoids for speed.
- **SO_REUSEPORT:** https://lwn.net/Articles/542629/ — kernel load-balancing used for flap multi-worker.

See also: [`PERFORMANCE.md`](PERFORMANCE.md) for benchmarks & flame graphs.
