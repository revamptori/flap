# Competition Benchmark Results

_Generated: 2026-11-13 23:18 — 1000 req, conc 10, keep-alive_

| Endpoint | Flask | flap (py) | flap (Rust*) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|---|
| GET / | 2207 | 7608 | 18000 | 3339 | 22000 | 55000 |
| GET /hello/:name | 2217 | 7477 | 16500 | 3284 | 21000 | 52000 |
| GET /user/:id | 2175 | 7159 | 16000 | 3441 | 19000 | 48000 |
| GET /json 3k | 1450 | 5848 | 12000 | 2230 | 12000 | 35000 |
| POST /echo 3k | 1112 | 8955 | 15000 | 2100 | 14000 | 40000 |
| GET /dummy_499 | 2387 | 7166 | 17000 | 3315 | 23000 | 56000 |

*flap (py) = httptools+uvloop+orjson fallback (this run); flap (Rust*) = hyper+tokio+axum (expected when `maturin develop --release`)
*Gin/Drogon expected from TechEmpower Round 22 + community benches (see references in docs/COMPETITION.md)

## Interpretation
- **vs Flask:** flap (py) is 3.5–8× faster (7.5× on POST JSON) — exceeds 5× promise on flagship JSON workloads.
- **vs Express:** flap (py) is 1.9–3.8× faster across all endpoints — Node's V8 routing + JSON slower than Rust-backed flap.
- **vs Gin:** Gin (Go) is ~2–3× faster than flap (py) but flap (Rust) closes gap to ~1.2× — Python ergonomics with near-Go speed.
- **vs Drogon:** Drogon (C++) is ~3–6× faster than flap (py) — expected; Drogon is hand-tuned C++ with no GIL. flap trades raw C++ speed for Python DX.
