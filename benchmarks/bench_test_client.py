"""
Test-client benchmark (no network) - Flask vs flap dispatch overhead only.
"""
import time

def run_test_client_bench(iterations=10000):
    # Flask
    from flask import Flask
    flask_app = Flask(__name__)

    @flask_app.route("/hello/<name>")
    def hello(name):
        return f"hello {name}"

    @flask_app.route("/user/<id>")
    def user(id):
        return {"id": id}

    flask_client = flask_app.test_client()

    # Flap
    from flap import Flap
    flap_app = Flap(__name__)

    @flap_app.get("/hello/<name>")
    def hello2(req, name):
        return f"hello {name}"

    @flap_app.get("/user/<id>")
    def user2(req, id):
        return {"id": id}

    flap_client = flap_app.test_client()

    # Warmup
    for _ in range(100):
        flask_client.get("/hello/world")
        flap_client.get("/hello/world")

    # Bench Flask
    t0 = time.perf_counter()
    for _ in range(iterations):
        flask_client.get("/hello/world")
    t_flask = time.perf_counter() - t0
    rps_flask = iterations / t_flask if t_flask else 0

    t0 = time.perf_counter()
    for _ in range(iterations):
        flap_client.get("/hello/world")
    t_flap = time.perf_counter() - t0
    rps_flap = iterations / t_flap if t_flap else 0

    speedup = rps_flap / rps_flask if rps_flask else 0
    print(f"Flask test client: {rps_flask:.0f} rps ({t_flask:.3f}s for {iterations})")
    print(f"Flap  test client: {rps_flap:.0f} rps ({t_flap:.3f}s for {iterations})")
    print(f"Speedup: {speedup:.2f}x  {'✅ PASS' if speedup >=5 else '❌ FAIL'}")

    # Second route with param
    t0 = time.perf_counter()
    for _ in range(iterations):
        flask_client.get("/user/123")
    t_flask2 = time.perf_counter() - t0
    rps_flask2 = iterations / t_flask2 if t_flask2 else 0

    t0 = time.perf_counter()
    for _ in range(iterations):
        flap_client.get("/user/123")
    t_flap2 = time.perf_counter() - t0
    rps_flap2 = iterations / t_flap2 if t_flap2 else 0

    speedup2 = rps_flap2 / rps_flask2 if rps_flask2 else 0
    print(f"\nFlask /user: {rps_flask2:.0f} rps  Flap /user: {rps_flap2:.0f} rps  Speedup {speedup2:.2f}x")

if __name__ == "__main__":
    run_test_client_bench()
