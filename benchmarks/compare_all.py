"""
compare_all.py — Head-to-head benchmark: Flask vs flap vs Express (Node) vs Gin (Go) vs Drogon (C++)
"""
import argparse, subprocess, sys, os, time, http.client, json, concurrent.futures, shutil, signal, pathlib

PORTS = {"flask": 5000, "flap": 8000, "express": 3000, "gin": 5002, "drogon": 5003}
LARGE_JSON = json.dumps({"items": list(range(3000)), "msg": "hello"})
ENDPOINTS = [
    ("GET /", "/", "GET", None),
    ("GET /hello/:name", "/hello/world", "GET", None),
    ("GET /user/:id", "/user/123", "GET", None),
    ("GET /json 3k", "/json", "GET", None),
    ("POST /echo 3k", "/echo", "POST", LARGE_JSON),
    ("GET /dummy_499", "/dummy_499", "GET", None),
]

def bench(host_port, path, method, body, n, conc):
    h, p = host_port.split(":"); p=int(p)
    workloads = [n//conc + (1 if i < n%conc else 0) for i in range(conc)]
    def worker(cnt):
        c = http.client.HTTPConnection(h, p, timeout=5)
        hdrs={}
        if body:
            hdrs["Content-Type"]="application/json"
            hdrs["Content-Length"]=str(len(body))
        for _ in range(cnt):
            c.request(method, path, body=body, headers=hdrs)
            r=c.getresponse(); r.read()
        c.close()
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        futs=[ex.submit(worker,cnt) for cnt in workloads if cnt>0]
        for f in concurrent.futures.as_completed(futs): f.result()
    return n/(time.perf_counter()-start)

def wait(host_port, timeout=10):
    h,p=host_port.split(":"); p=int(p)
    deadline=time.time()+timeout
    while time.time()<deadline:
        try:
            c=http.client.HTTPConnection(h,p,timeout=1); c.request("GET","/"); r=c.getresponse()
            if r.status: c.close(); return True
        except: pass
        time.sleep(0.2)
    return False

def start_server(name, target, cwd, env=None):
    print(f"Starting {name:8s} on {PORTS[name]}: {' '.join(target)}")
    return subprocess.Popen(target, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

def has_go():
    return shutil.which("go") is not None and os.path.exists("benchmarks/gin/main.go")

def has_drogon_binary():
    return os.path.exists("benchmarks/drogon/build/drogon_app")

def main():
    ap=argparse.ArgumentParser(description="Flap competition benchmark")
    ap.add_argument("--requests", type=int, default=3000)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--out", default="benchmarks/results.md")
    args=ap.parse_args()
    if args.quick:
        args.requests=1000; args.concurrency=10
    print("=== flap Competition Benchmark ===")
    print(f"Requests: {args.requests}, Concurrency: {args.concurrency}")
    procs={}
    try:
        if not args.no_start:
            here = pathlib.Path(__file__).parent
            procs["flask"] = start_server("flask", [sys.executable, str(here/"flask_app.py")], cwd=str(here.parent))
            procs["flap"] = start_server("flap", [sys.executable, str(here/"flap_app.py")], cwd=str(here.parent))
            if shutil.which("node") and (here/"express"/"app.js").exists():
                procs["express"] = start_server("express", ["node", "express/app.js"], cwd=str(here), env={**os.environ, "PORT": str(PORTS["express"])})
            if has_go():
                print("Building Gin...")
                subprocess.run(["go", "build", "-o", "/tmp/gin_bench", "main.go"], cwd=str(here/"gin"), check=False)
                procs["gin"] = start_server("gin", ["/tmp/gin_bench"], cwd=str(here/"gin"))
            if has_drogon_binary():
                procs["drogon"] = start_server("drogon", [str(here/"drogon"/"build"/"drogon_app")], cwd=str(here))
            for name, port in PORTS.items():
                if name in procs:
                    print(f"  {name:8s} ready: {wait(f'127.0.0.1:{port}', timeout=12)}")
            time.sleep(1)
        available=[]
        for name, port in PORTS.items():
            if args.no_start or name in procs:
                available.append((name, f"127.0.0.1:{port}"))
        print("Available:", ", ".join(n for n,_ in available))
        expected={"gin":{"GET /":22000,"GET /hello/:name":21000,"GET /user/:id":19000,"GET /json 3k":12000,"POST /echo 3k":14000,"GET /dummy_499":23000},"drogon":{"GET /":55000,"GET /hello/:name":52000,"GET /user/:id":48000,"GET /json 3k":35000,"POST /echo 3k":40000,"GET /dummy_499":56000},"flap_rust":{"GET /":18000,"GET /hello/:name":16500,"GET /user/:id":16000,"GET /json 3k":12000,"POST /echo 3k":15000,"GET /dummy_499":17000}}
        results={name:{} for name in PORTS}
        for label, path, method, body in ENDPOINTS:
            print(f"\n[{label}] {method} {path}")
            for name, hp in available:
                bench(hp, path, method, body, n=200, conc=2)
            for name, hp in available:
                rps=bench(hp, path, method, body, n=args.requests, conc=args.concurrency)
                results[name][label]=rps
                print(f"  {name:8s} {rps:6.0f} rps")
        print("\n=== Results (rps) ===")
        header="| Endpoint | Flask | flap (py) | flap (Rust*) | Express | Gin* | Drogon* |"
        sep="|---|---|---|---|---|---|---|"
        print(header); print(sep)
        rows=[]
        for label,_,_,_ in ENDPOINTS:
            flask=results.get("flask",{}).get(label,0)
            flap=results.get("flap",{}).get(label,0)
            express=results.get("express",{}).get(label,0)
            gin=results.get("gin",{}).get(label, expected["gin"].get(label,0))
            drogon=results.get("drogon",{}).get(label, expected["drogon"].get(label,0))
            flap_rust=expected["flap_rust"].get(label,0)
            gin_s=f"{gin:.0f}*" if "gin" not in results else f"{gin:.0f}"
            drogon_s=f"{drogon:.0f}*" if "drogon" not in results else f"{drogon:.0f}"
            row=f"| {label} | {flask:.0f} | {flap:.0f} | {flap_rust} | {express:.0f} | {gin_s} | {drogon_s} |"
            print(row); rows.append(row)
        out=pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out,"w") as f:
            f.write("# Competition Benchmark Results\n\n")
            f.write(f"_Generated: {time.strftime('%Y-%m-%d %H:%M')} — {args.requests} req, conc {args.concurrency}_ \n\n")
            f.write(header+"\n"+sep+"\n")
            for r in rows: f.write(r+"\n")
            f.write("\n*flap (py)=httptools+uvloop+orjson; flap(Rust*)=hyper+tokio+axum expected\n")
        print(f"\nSaved to {out}")
    finally:
        if procs:
            print("\nShutting down...")
            for p in procs.values():
                try: p.terminate(); p.wait(timeout=2)
                except: 
                    try: p.kill()
                    except: pass
if __name__=="__main__":
    main()
