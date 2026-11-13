import pytest
from flap import Flap

def test_simple_get():
    app = Flap(__name__)
    @app.get("/")
    def home(req):
        return "hello"
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert r.text == "hello"

def test_path_param():
    app = Flap(__name__)
    @app.get("/hello/<name>")
    def hello(req, name):
        return f"hello {name}"
    c = app.test_client()
    assert c.get("/hello/world").text == "hello world"
    assert c.get("/hello/Ada").text == "hello Ada"

def test_int_param():
    app = Flap(__name__)
    @app.get("/post/<int:id>")
    def get_post(req, id):
        assert isinstance(id, int)
        return {"id": id}
    c = app.test_client()
    r = c.get("/post/123")
    assert r.status_code == 200
    assert r.json() == {"id": 123}
    # non-int should 404
    r2 = c.get("/post/abc")
    assert r2.status_code == 404

def test_query_params():
    app = Flap(__name__)
    @app.get("/search")
    def search(req):
        return {"q": req.query.get("q", ""), "lang": req.query.get("lang", "en")}
    c = app.test_client()
    r = c.get("/search?q=flap&lang=en")
    assert r.json() == {"q": "flap", "lang": "en"}

def test_post_json():
    app = Flap(__name__)
    @app.post("/echo")
    def echo(req):
        return req.json()
    c = app.test_client()
    r = c.post("/echo", json={"a": 1, "b": 2})
    assert r.status_code == 200
    assert r.json() == {"a": 1, "b": 2}

def test_json_response():
    app = Flap(__name__)
    @app.get("/data")
    def data(req):
        return {"msg": "ok", "items": [1,2,3]}
    c = app.test_client()
    r = c.get("/data")
    assert r.status_code == 200
    assert r.json() == {"msg": "ok", "items": [1,2,3]}

def test_status_and_headers():
    app = Flap(__name__)
    @app.get("/created")
    def created(req):
        return {"id": 1}, 201
    @app.get("/custom")
    def custom(req):
        return {"ok": True}, 200, {"X-Custom": "123"}
    c = app.test_client()
    r = c.get("/created")
    assert r.status_code == 201
    r2 = c.get("/custom")
    assert r2.status_code == 200
    assert r2.headers.get("X-Custom") == "123"

def test_404():
    app = Flap(__name__)
    @app.get("/exists")
    def exists(req):
        return "yes"
    c = app.test_client()
    r = c.get("/missing")
    assert r.status_code == 404

def test_before_request_hook():
    app = Flap(__name__)
    @app.before_request
    def auth(req):
        if req.path.startswith("/private"):
            return {"error": "unauthorized"}, 401
    @app.get("/private/data")
    def data(req):
        return {"secret": True}
    @app.get("/public")
    def public(req):
        return {"public": True}
    c = app.test_client()
    assert c.get("/private/data").status_code == 401
    assert c.get("/public").status_code == 200

def test_after_request_hook():
    app = Flap(__name__)
    @app.after_request
    def add_header(req, status, headers, body):
        headers["X-Frame"] = "1"
        return status, headers, body, None
    @app.get("/")
    def home(req):
        return "hi"
    c = app.test_client()
    r = c.get("/")
    assert r.headers.get("X-Frame") == "1"

def test_redirect():
    from flap import redirect
    app = Flap(__name__)
    @app.get("/old")
    def old(req):
        return redirect("/new")
    c = app.test_client()
    r = c.get("/old")
    assert r.status_code == 302
    assert r.headers.get("Location") == "/new"

def test_multiple_methods():
    app = Flap(__name__)
    @app.route("/multi", methods=["GET", "POST"])
    def multi(req):
        return {"method": req.method}
    c = app.test_client()
    assert c.get("/multi").json() == {"method": "GET"}
    assert c.post("/multi").json() == {"method": "POST"}

def test_path_capture():
    app = Flap(__name__)
    @app.get("/files/<path:filepath>")
    def files(req, filepath):
        return {"path": filepath}
    c = app.test_client()
    assert c.get("/files/a/b/c.txt").json() == {"path": "a/b/c.txt"}

def test_large_json():
    app = Flap(__name__)
    @app.post("/large")
    def large(req):
        data = req.json()
        return {"len": len(data["items"])}
    c = app.test_client()
    payload = {"items": list(range(1000))}
    r = c.post("/large", json=payload)
    assert r.json()["len"] == 1000
