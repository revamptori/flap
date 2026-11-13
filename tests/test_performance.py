"""
Performance regression test: ensure flap stays ≥5x faster than Flask.
This test is run in CI; it benchmarks test-client dispatch (no network)
and fails if flap is not at least 5x faster.

To run: pytest tests/test_performance.py -s
"""
import time

def test_flap_vs_flask_speed():
    try:
        from flask import Flask
    except ImportError:
        print("Flask not available, skipping perf test")
        return

    from flap import Flap

    iterations = 5000

    # Flask setup
    flask_app = Flask(__name__)
    @flask_app.route("/hello/<name>")
    def f_hello(name):
        return f"hello {name}"
    @flask_app.route("/user/<id>")
    def f_user(id):
        return {"id": id}
    @flask_app.route("/json")
    def f_json():
        return {"msg": "hi", "items": [1,2,3]}

    flask_c = flask_app.test_client()

    # Flap setup
    flap_app = Flap(__name__)
    @flap_app.get("/hello/<name>")
    def p_hello(req, name):
        return f"hello {name}"
    @flap_app.get("/user/<id>")
    def p_user(req, id):
        return {"id": id}
    @flap_app.get("/json")
    def p_json(req):
        return {"msg": "hi", "items": [1,2,3]}

    flap_c = flap_app.test_client()

    def bench(label, flask_path, flap_path):
        # warmup
        for _ in range(50):
            flask_c.get(flask_path)
            flap_c.get(flap_path)

        t0 = time.perf_counter()
        for _ in range(iterations):
            flask_c.get(flask_path)
        t_flask = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(iterations):
            flap_c.get(flap_path)
        t_flap = time.perf_counter() - t0

        rps_flask = iterations / t_flask if t_flask else 0
        rps_flap = iterations / t_flap if t_flap else 0
        speedup = rps_flap / rps_flask if rps_flask else 0
        print(f"{label}: Flask {rps_flask:.0f} rps, flap {rps_flap:.0f} rps, {speedup:.2f}x")
        return speedup

    results = []
    results.append(bench("GET /hello/<name>", "/hello/world", "/hello/world"))
    results.append(bench("GET /user/<id>", "/user/123", "/user/123"))
    results.append(bench("GET /json", "/json", "/json"))

    for sp in results:
        assert sp >= 5.0, f"Performance regression: flap only {sp:.2f}x faster than Flask (need ≥5x). Ensure orjson+httptools installed."
