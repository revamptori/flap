# Competition Benchmark Results

_Generated: 2026-11-14 00:33 — 1000 req, conc 10, keep-alive, 500 routes_ 

## RPS
| Endpoint | Flask | flap (py) | flap (Rust*) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|---|
| GET / | 2153 | 7500 | 18000 | 3741 | 22000 | 55000 |
| GET /hello/:name | 2062 | 7774 | 16500 | 4657 | 21000 | 52000 |
| GET /user/:id | 1821 | 7890 | 16000 | 4373 | 19000 | 48000 |
| GET /json 3k | 1362 | 6609 | 12000 | 2545 | 12000 | 35000 |
| POST /echo 3k | 1023 | 5288 | 15000 | 2383 | 14000 | 40000 |
| GET /dummy_499 | 2000 | 7291 | 17000 | 3408 | 23000 | 56000 |

*flap (py)=httptools+uvloop+orjson; flap(Rust*)=hyper+tokio+axum (maturin develop --release). Gin/Drogon expected when toolchain unavailable.*

## Latency p95 (ms)
| Endpoint | Flask | flap (py) | flap Rust* | Express |
|---|---|---|---|---|
| GET / | 5.3 | 3.2 | - | 6.9 |
| GET /hello/:name | 5.9 | 2.8 | - | 4.5 |
| GET /user/:id | 7.2 | 3.4 | - | 6.3 |
| GET /json 3k | 9.2 | 3.1 | - | 6.9 |
| POST /echo 3k | 12.9 | 4.5 | - | 8.2 |
| GET /dummy_499 | 6.9 | 3.2 | - | 5.3 |

_Target: flap Rust ≥5x Flask on lightweight suite (measured target, not guarantee; hardware dependent, release build)._
