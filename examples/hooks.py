"""Middleware hooks example: auth + CORS"""
from flap import Flap

app = Flap(__name__)

@app.before_request
def auth(req):
    # Simple token check for /private/*
    if req.path.startswith("/private"):
        token = req.header("x-token")
        if token != "secret":
            return {"error": "unauthorized"}, 401

@app.after_request
def cors(req, status, headers, body):
    headers["Access-Control-Allow-Origin"] = "*"
    headers["X-Powered-By"] = "flap"
    return status, headers, body, None

@app.get("/")
def home(req):
    return "public hello"

@app.get("/private/data")
def private(req):
    return {"secret": "42"}

@app.get("/hello/<name>")
def hello(req, name):
    return f"hello {name}"

if __name__ == "__main__":
    print("Try:")
    print("  curl http://localhost:8000/private/data -> 401")
    print("  curl http://localhost:8000/private/data -H 'X-Token: secret' -> 200")
    app.run(port=8000)
