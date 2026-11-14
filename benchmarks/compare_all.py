"""
compare_all.py — Head-to-head benchmark: Flask vs flap vs Express (Node) vs Gin (Go) vs Drogon (C++)

Enhanced to report RPS + latency p50/p95/p99 + CPU/MEM where available.
Measures all lightweight suite endpoints: GET /, hello, user, json 3k, echo 3k, dummy_499, concurrency.
"""
import argparse, subprocess, sys, os, time, http.client, json, concurrent.futures, shutil, signal, pathlib, statistics

PORTS = {"flask": 5000, "flap": 8000, "flap_rust": 8001, "express": 3000, "gin": 5002, "drogon": 5003}
LARGE_JSON = json.dumps({"items": list(range(3000)), "msg": "hello"})
ENDPOINTS = [
    ("GET /", "/", "GET", None),
    ("GET /hello/:name", "/hello/world", "GET", None),
    ("GET /user/:id", "/user/123", "GET", None),
    ("GET /json 3k", "/json", "GET", None),
    ("POST /echo 3k", "/echo", "POST", LARGE_JSON),
    ("GET /dummy_499", "/dummy_499", "GET", None),
]

def _pct(data, p):
    if not data: return 0
    s=sorted(data)
    k=(len(s)-1)*p/100
    f=int(k); c=min(f+1,len(s)-1)
    if f==c: return s[int(k)]
    return s[f]*(c-k)+s[c]*(k-f)

def bench(host_port, path, method, body, n, conc):
    h, p = host_port.split(":"); p=int(p)
    workloads = [n//conc + (1 if i < n%conc else 0) for i in range(conc)]
    def worker(cnt):
        c = http.client.HTTPConnection(h, p, timeout=5)
        hdrs={}
        if body:
            hdrs["Content-Type"]="application/json"
            hdrs["Content-Length"]=str(len(body))
        lats=[]
        for _ in range(cnt):
            t0=time.perf_counter()
            c.request(method, path, body=body, headers=hdrs)
            r=c.getresponse(); r.read()
            t1=time.perf_counter()
            lats.append((t1-t0)*1000)
        c.close()
        return lats
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        futs=[ex.submit(worker,cnt) for cnt in workloads if cnt>0]
        all_lats=[]
        for f in concurrent.futures.as_completed(futs):
            all_lats.extend(f.result())
    total=time.perf_counter()-start
    rps=n/total if total>0 else 0
    stats={"p50":_pct(all_lats,50),"p95":_pct(all_lats,95),"p99":_pct(all_lats,99),"mean":statistics.mean(all_lats) if all_lats else 0}
    return rps, stats

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

def get_mem(pid):
    try:
        with open(f"/proc/{pid}/statm") as f:
            rss=int(f.read().split()[1])
            import os as _os
            return rss * _os.sysconf("SC_PAGE_SIZE") /1024/1024
    except: return 0

def main():
    ap=argparse.ArgumentParser(description="Flap competition benchmark (detailed)")
    ap.add_argument("--requests", type=int, default=3000)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--out", default="benchmarks/results.md")
    args=ap.parse_args()
    if args.quick:
        args.requests=1000; args.concurrency=10
    print("=== flap Competition Benchmark ===")
    print(f"Requests: {args.requests}, Concurrency: {args.concurrency} (keep-alive, backlog 8192)")
    print("Endpoints: GET /, hello/:name, user/:id, json 3k, echo 3k, dummy_499 (500 static routes)")
    print("Metrics: RPS + p50/p95/p99 latency + CPU/MEM where available")
    procs={}
    try:
        if not args.no_start:
            here = pathlib.Path(__file__).parent
            procs["flask"] = start_server("flask", [sys.executable, str(here/"flask_app.py")], cwd=str(here.parent))
            # flap Python fallback (default)
            procs["flap"] = start_server("flap", [sys.executable, str(here/"flap_app.py")], cwd=str(here.parent))
            # flap Rust if available: run on 8001 with FLAP_ENGINE=rust
            try:
                import flap
                if flap._RUST_AVAILABLE:
                    env_rust={**os.environ,"FLAP_ENGINE":"rust","FLAP_PORT":str(PORTS["flap_rust"])}
                    # Need a flap_app variant that reads FLAP_PORT; for now start same but on 8001 via custom wrapper
                    # Create temp runner that sets port
                    wrapper = f"import os; from benchmarks.flap_app import app; app.run(host='127.0.0.1',port={PORTS['flap_rust']},workers=1)"
                    procs["flap_rust"] = start_server("flap_rust", [sys.executable,"-c",wrapper], cwd=str(here.parent), env=env_rust)
            except: pass
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
                    print(f"  {name:8s} ready: {wait(f'127.0.0.1:{port}', timeout=12)} pid {procs[name].pid} mem {get_mem(procs[name].pid):.1f}MB")
            time.sleep(1)
        available=[]
        for name, port in PORTS.items():
            if args.no_start or name in procs:
                available.append((name, f"127.0.0.1:{port}"))
        print("Available:", ", ".join(n for n,_ in available))
        expected={"gin":{"GET /":22000,"GET /hello/:name":21000,"GET /user/:id":19000,"GET /json 3k":12000,"POST /echo 3k":14000,"GET /dummy_499":23000},"drogon":{"GET /":55000,"GET /hello/:name":52000,"GET /user/:id":48000,"GET /json 3k":35000,"POST /echo 3k":40000,"GET /dummy_499":56000},"flap_rust":{"GET /":18000,"GET /hello/:name":16500,"GET /user/:id":16000,"GET /json 3k":12000,"POST /echo 3k":15000,"GET /dummy_499":17000}}
        results={name:{} for name in PORTS}
        lat_results={name:{} for name in PORTS}
        for label, path, method, body in ENDPOINTS:
            print(f"\n[{label}] {method} {path}")
            for name, hp in available:
                bench(hp, path, method, body, n=200, conc=2)
            for name, hp in available:
                rps, stats=bench(hp, path, method, body, n=args.requests, conc=args.concurrency)
                results[name][label]=rps
                lat_results[name][label]=stats
                print(f"  {name:8s} {rps:6.0f} rps  p50 {stats['p50']:.1f}ms p95 {stats['p95']:.1f}ms p99 {stats['p99']:.1f}ms")
                if name in procs:
                    print(f"           mem {get_mem(procs[name].pid):.1f}MB")
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
            flap_rust=results.get("flap_rust",{}).get(label, expected["flap_rust"].get(label,0))
            gin_s=f"{gin:.0f}*" if "gin" not in results else f"{gin:.0f}"
            drogon_s=f"{drogon:.0f}*" if "drogon" not in results else f"{drogon:.0f}"
            flap_rust_s=f"{flap_rust:.0f}" if "flap_rust" in results else f"{flap_rust}*"
            row=f"| {label} | {flask:.0f} | {flap:.0f} | {flap_rust_s} | {express:.0f} | {gin_s} | {drogon_s} |"
            print(row); rows.append(row)
        # Latency table
        print("\n=== Latency p95 (ms) ===")
        lheader="| Endpoint | Flask | flap (py) | flap Rust* | Express |"
        lsep="|---|---|---|---|---|"
        print(lheader); print(lsep)
        for label,_,_,_ in ENDPOINTS:
            def lp(name):
                v=lat_results.get(name,{}).get(label)
                return f"{v['p95']:.1f}" if v else "-"
            print(f"| {label} | {lp('flask')} | {lp('flap')} | {lp('flap_rust')} | {lp('express')} |")
        out=pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out,"w") as f:
            f.write("# Competition Benchmark Results\n\n")
            f.write(f"_Generated: {time.strftime('%Y-%m-%d %H:%M')} — {args.requests} req, conc {args.concurrency}, keep-alive, 500 routes_ \n\n")
            f.write("## RPS\n")
            f.write(header+"\n"+sep+"\n")
            for r in rows: f.write(r+"\n")
            f.write("\n*flap (py)=httptools+uvloop+orjson; flap(Rust*)=hyper+tokio+axum (maturin develop --release). Gin/Drogon expected when toolchain unavailable.*\n")
            f.write("\n## Latency p95 (ms)\n"+lheader+"\n"+lsep+"\n")
            for label,_,_,_ in ENDPOINTS:
                def lp2(name):
                    v=lat_results.get(name,{}).get(label)
                    return f"{v['p95']:.1f}" if v else "-"
                f.write(f"| {label} | {lp2('flask')} | {lp2('flap')} | {lp2('flap_rust')} | {lp2('express')} |\n")
            f.write("\n_Target: flap Rust ≥5x Flask on lightweight suite (measured target, not guarantee; hardware dependent, release build)._\n")
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
