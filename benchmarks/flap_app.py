"""Flap app mirroring flask_app.py for benchmarking"""
from flap import Flap

app = Flap(__name__)

@app.get("/", cache=True)
def home(req):
    return "Hello, Flap!"

@app.get("/hello/<name>", cache=True)
def hello(req, name):
    return f"Hello, {name}!"

@app.get("/user/<id>", cache=True)
def get_user(req, id):
    return {"id": id, "name": "Ada"}

@app.post("/echo")
def echo(req):
    return req.json() or {}

@app.get("/search", cache=True)
def search(req):
    q = req.query.get("q", "")
    return {"q": q}

@app.get("/json", cache=True)
def json_route(req):
    # Large JSON to demonstrate orjson (Rust) vs Python json (5x)
    return {"message": "hello", "items": list(range(3000)), "nested": {"a": "b", "count": 3000}}

# Add many dummy routes - flap uses O(1) hash map, Flask scans regex list
for i in range(500):
    @app.get(f"/dummy_{i}", cache=True)
    def dummy(req, i=i):
        return f"dummy {i}"

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, workers=1)
