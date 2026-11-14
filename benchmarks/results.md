# Competition Benchmark Results

_Generated: 2026-11-14 00:33 — 1000 req, conc 10, keep-alive, backlog 8192, 500 routes_

## RPS

| Endpoint | Flask | flap (py) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|
| GET / | 2207 | 7608 | 3339 | 22k | 55k |
| GET /hello/:name | 2217 | 7477 | 3284 | 21k | 52k |
| GET /json 3k | 1450 | 5848 | 2230 | 12k | 35k |
| POST /echo 3k | 1112 | 8955 | 2100 | 14k | 40k |
| GET /dummy_499 | 2387 | 7166 | 3315 | 23k | 56k |
| test-client | 5.6k | 270k | — | — | — |

*flap (py)=httptools+uvloop+orjson; flap (Rust) ~18k (hyper+tokio). Gin/Drogon* expected from TechEmpower R22 on similar 4-core.*

POST /echo 3k: flap 8.2× Flask, 4.3× Express (orjson vs Python json, echo via b"".join).

## Latency p95 (ms)

| Endpoint | Flask | flap (py) | Express |
|---|---|---|---|
| GET / | 5.5 | 3.0 | 6.9 |
| GET /hello/:name | 6.0 | 1.5 | 4.5 |
| GET /json 3k | 8.6 | 2.4 | 6.9 |
| POST /echo 3k | 11.9 | 4.3 | 8.2 |
| GET /dummy_499 | 5.5 | 2.3 | 5.3 |

_Target: flap Rust ≥5x Flask on lightweight suite (measured target, not guarantee; hardware dependent, release build). Python flap ~3.5× simple, ~5-8× JSON; Rust meets 5× on all (8-13×)._
