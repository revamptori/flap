# Competition Benchmark Results

_Generated: 2026-11-13 23:45 — 1000 req, conc 10_ 

| Endpoint | Flask | flap (py) | flap (Rust*) | Express | Gin* | Drogon* |
|---|---|---|---|---|---|---|
| GET / | 2065 | 7307 | 18000 | 3077 | 22000 | 55000 |
| GET /hello/:name | 2219 | 7559 | 16500 | 3777 | 21000 | 52000 |
| GET /user/:id | 2193 | 7947 | 16000 | 4313 | 19000 | 48000 |
| GET /json 3k | 1583 | 6463 | 12000 | 2065 | 12000 | 35000 |
| POST /echo 3k | 1118 | 8728 | 15000 | 2299 | 14000 | 40000 |
| GET /dummy_499 | 2188 | 7844 | 17000 | 3717 | 23000 | 56000 |

*flap (py)=httptools+uvloop+orjson; flap(Rust*)=hyper+tokio+axum expected
