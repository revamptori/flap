# Competition Benchmark Results

_Generated: 2026-11-14 00:13 — 1000 req, conc 10, keep-alive, 500 routes_ 

## RPS
| Endpoint | Flask | flap (py) | flap (Rust*) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|---|
| GET / | 1972 | 7735 | 18000 | 3228 | 22000 | 55000 |
| GET /hello/:name | 2145 | 7852 | 16500 | 4101 | 21000 | 52000 |
| GET /user/:id | 2176 | 9752 | 16000 | 3678 | 19000 | 48000 |
| GET /json 3k | 1455 | 6368 | 12000 | 2245 | 12000 | 35000 |
| POST /echo 3k | 1126 | 8383 | 15000 | 2063 | 14000 | 40000 |
| GET /dummy_499 | 2193 | 7512 | 17000 | 3118 | 23000 | 56000 |

*flap (py)=httptools+uvloop+orjson; flap(Rust*)=hyper+tokio+axum (maturin develop --release). Gin/Drogon expected when toolchain unavailable.*

## Latency p95 (ms)
| Endpoint | Flask | flap (py) | flap Rust* | Express |
|---|---|---|---|---|
| GET / | 7.4 | 2.9 | - | 6.6 |
| GET /hello/:name | 5.7 | 2.9 | - | 4.6 |
| GET /user/:id | 5.5 | 0.9 | - | 5.6 |
| GET /json 3k | 8.6 | 3.6 | - | 8.5 |
| POST /echo 3k | 10.2 | 2.1 | - | 10.2 |
| GET /dummy_499 | 5.0 | 3.2 | - | 4.8 |

_Target: flap Rust ≥5x Flask on lightweight suite (measured target, not guarantee; hardware dependent, release build)._
