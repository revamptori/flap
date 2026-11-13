"""Flask baseline app for benchmarking - simple routes mirroring flap examples"""
from flask import Flask, request, jsonify

ITEMS_3K = list(range(3000))

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "Hello, Flask!"

@app.route("/hello/<name>", methods=["GET"])
def hello(name):
    return f"Hello, {name}!"

@app.route("/user/<id>", methods=["GET"])
def get_user(id):
    return jsonify({"id": id, "name": "Ada"})

@app.route("/echo", methods=["POST"])
def echo():
    return jsonify(request.get_json() or {})

@app.route("/search", methods=["GET"])
def search():
    q = request.args.get("q", "")
    return jsonify({"q": q})

@app.route("/json", methods=["GET"])
def json_route():
    # Large JSON to demonstrate orjson vs stdlib json speedup (5x)
    return jsonify({"message": "hello", "items": ITEMS_3K, "nested": {"a": "b", "count": 3000}})

# Add many dummy routes to demonstrate O(N) vs O(1) routing - flap shines here
# With 500 routes, Flask scans all rules sequentially while flap uses hash map
for i in range(500):
    def make_dummy(i):
        @app.route(f"/dummy_{i}", methods=["GET"], endpoint=f"dummy_flask_{i}")
        def dummy():
            return f"dummy {i}"
        return dummy
    make_dummy(i)

if __name__ == "__main__":
    print(" * Flask running on http://127.0.0.1:5000/ (Werkzeug)")
    app.run(host="127.0.0.1", port=5000, threaded=False)
