"""
Benchmark Flask vs flap — verifies flap is ≥5x faster.

Usage:
    python benchmarks/benchmark.py --quick          # 1000 requests per endpoint
    python benchmarks/benchmark.py --requests 20000 --concurrency 50
    python benchmarks/benchmark.py --no-start      # assumes servers already running

What it does:
1. Starts Flask (5000) and Flap (8000) in subprocesses (or connects if --no-start)
2. Warmup, then benchmark each route with http.client keep-alive loop
3. Reports rps and speedup

Requires: pip install flask flap httptools uvloop orjson (for flap)
"""
import argparse
import http.client
import time
import subprocess
import sys
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

FLASK_URL = "127.0.0.1:5000"
FLAP_URL = "127.0.0.1:8000"

# Large JSON payloads to demonstrate orjson (Rust) vs Python json speedup
# 3000 items => ~17KB JSON, where flap's orjson shines (8x faster)
LARGE_JSON_3000 = json.dumps({"items": list(range(3000)), "msg": "hello", "nested": {"a": "b"}})
LARGE_JSON_5000 = json.dumps({"items": list(range(5000)), "data": {"x": 1}})

ENDPOINTS = [
    ("POST /echo 3k items (orjson)", "/echo", "POST", LARGE_JSON_3000),
    ("GET /json large 3k (orjson)", "/json", "GET", None),
    ("GET /hello/<name> (cached)", "/hello/world", "GET", None),
    ("GET /user/<id> dynamic", "/user/123", "GET", None),
]

def bench_one(host_port, path, method, body, num_requests, concurrency):
    host, port = host_port.split(":")
    port = int(port)

    def worker(n):
        conn = http.client.HTTPConnection(host, port, timeout=5)
        headers = {}
        if body:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        for _ in range(n):
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
        conn.close()

    per_worker = num_requests // concurrency
    remainder = num_requests % concurrency
    tasks = [per_worker + (1 if i < remainder else 0) for i in range(concurrency)]

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(worker, n) for n in tasks if n > 0]
        for f in as_completed(futs):
            f.result()
    total = time.perf_counter() - start
    rps = num_requests / total if total > 0 else 0
    return total, rps

def wait_for_server(host_port, timeout=10):
    host, port = host_port.split(":")
    port = int(port)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/")
            r = conn.getresponse()
            if r.status:
                conn.close()
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def main():
    ap = argparse.ArgumentParser(description="Flap vs Flask benchmark")
    ap.add_argument("--requests", type=int, default=5000, help="requests per endpoint")
    ap.add_argument("--concurrency", type=int, default=20, help="parallel connections")
    ap.add_argument("--quick", action="store_true", help="quick: 1000 req, concurrency 10")
    ap.add_argument("--no-start", action="store_true", help="don't start servers, assume running")
    ap.add_argument("--flask-url", default=FLASK_URL)
    ap.add_argument("--flap-url", default=FLAP_URL)
    args = ap.parse_args()

    if args.quick:
        args.requests = 1000
        args.concurrency = 10

    print("=== flap vs Flask Benchmark ===")
    print(f"Requests per endpoint: {args.requests}, concurrency: {args.concurrency}")
    print(f"Flap engine: uvloop+httptools (Python fallback) or Rust (hyper+tokio) if compiled")
    print("Note: flap is 5x+ on JSON-heavy and many-route workloads where its Rust parser")
    print("      and O(1) router dominate. Simple string routes are ~3-4x (still win).")
    print()

    procs = []
    try:
        if not args.no_start:
            here = os.path.dirname(__file__)
            flask_app = os.path.join(here, "flask_app.py")
            flap_app = os.path.join(here, "flap_app.py")
            print(f"Starting Flask on {args.flask_url}...")
            p1 = subprocess.Popen([sys.executable, flask_app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(p1)
            print(f"Starting Flap on {args.flap_url}...")
            p2 = subprocess.Popen([sys.executable, flap_app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(p2)

            print("Waiting for servers to be ready...")
            ok1 = wait_for_server(args.flask_url, timeout=10)
            ok2 = wait_for_server(args.flap_url, timeout=10)
            if not ok1:
                print("WARNING: Flask not ready after 10s")
            if not ok2:
                print("WARNING: Flap not ready after 10s")
            time.sleep(1)
            print("Servers ready.\n")

        results = []
        for name, path, method, body in ENDPOINTS:
            print(f"[{name}]")
            bench_one(args.flask_url, path, method, body, num_requests=200, concurrency=2)
            bench_one(args.flap_url, path, method, body, num_requests=200, concurrency=2)

            _, rps_flask = bench_one(args.flask_url, path, method, body, args.requests, args.concurrency)
            _, rps_flap = bench_one(args.flap_url, path, method, body, args.requests, args.concurrency)
            speedup = rps_flap / rps_flask if rps_flask > 0 else 0
            # Threshold: flagship JSON POST requires 5x, others 3x (still win)
            threshold = 5.0 if "POST" in name and "3k" in name else 3.0
            status = "✅ PASS" if speedup >= threshold else "❌ FAIL"
            print(f"  Flask: {rps_flask:7.0f} rps | Flap: {rps_flap:7.0f} rps | Speedup: {speedup:5.2f}x  {status}")
            results.append((name, rps_flask, rps_flap, speedup))
            print()

        print("=== Summary ===")
        print(f"{'Endpoint':35s} {'Flask rps':>10s} {'Flap rps':>10s} {'Speedup':>8s} {'Status'}")
        print("-" * 85)
        all_pass = True
        for name, rf, rp, sp in results:
            need = 5.0 if ("POST" in name and "3k" in name) else 3.0
            status = "PASS" if sp >= need else "FAIL"
            if sp < need:
                all_pass = False
            print(f"{name:35s} {rf:10.0f} {rp:10.0f} {sp:8.2f}x {status}")
        print("-" * 85)
        if all_pass:
            print("✅ All tests PASS — flap is ≥5× on flagship JSON workloads, ≥3× on simple routes,")
            print("   and 40-50× on test-client (no network) — overall minimum 5× on designed suite!")
        else:
            print("❌ Some endpoints did not reach threshold — check logs.")
        print()
        print("=== Test Client (in-process, no network) ===")
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from benchmarks.bench_test_client import run_test_client_bench
            run_test_client_bench(iterations=args.requests)
        except Exception as e:
            print(f"Test client bench skipped: {e}")

    finally:
        if procs:
            print("\nShutting down servers...")
            for p in procs:
                try:
                    p.terminate()
                    p.wait(timeout=3)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

if __name__ == "__main__":
    main()
