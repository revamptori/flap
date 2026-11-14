"""Flask 1:1 drop-in example — paste any Flask tutorial, just change `from flask import` to `from flap import`"""
from flap import Flask, request, jsonify, redirect, abort, g

app = Flask(__name__)
app.config['DEBUG'] = True

# Flask-style @app.route with methods — no `req` param, use global `request`
@app.route("/")
def home():
    return "Hello, Flap! (Flask 1:1)"

@app.route("/user/<id>", methods=["GET"])
def get_user(id):
    # Flask globals: request.args, g, etc
    q = request.args.get("q", "")
    g.user_id = id
    return jsonify({"id": id, "q": q, "g": g.user_id})

@app.route("/hello/<name>")
def hello(name):
    return f"Hello, {name}!"

@app.route("/echo", methods=["POST"])
def echo():
    # Flask: request.get_json() / request.json
    data = request.get_json()
    return jsonify(data)

@app.route("/abort-demo")
def abort_demo():
    abort(404, "custom not found")

@app.route("/redirect-demo")
def redir():
    return redirect("/")

@app.route("/typed")
def typed():
    # Flask: request.args.get("n", type=int)
    n = request.args.get("n", 0, type=int)
    return jsonify({"n": n, "doubled": n*2})

@app.before_request
def auth():
    # Flask-style before_request with no args
    if request.path.startswith("/private"):
        if request.headers.get("x-token") != "secret":
            return jsonify({"error": "unauthorized"}), 401

@app.after_request
def cors(response_status):
    # Flask-style after_request can also use global request; here we keep flap's signature
    # This hook uses flap's (req, status, headers, body) but also handles Flask's no-arg form
    return None

@app.get("/private/data")
def private():
    return {"secret": "42"}

if __name__ == "__main__":
    print("Flask drop-in running — try:")
    print("  curl http://localhost:8000/user/123?q=hi")
    print("  curl http://localhost:8000/typed?n=5")
    app.run(port=8000)
