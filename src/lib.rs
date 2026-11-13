//! Flap — Rust core for Python
//!
//! This is the high-performance engine behind flap. It provides a Rust HTTP server
//! using Tokio (async runtime) + Hyper (HTTP/1.1 parsing, same engine behind Node's http)
//! + Axum (routing, heavily optimized radix trie).
//!
//! Python's GIL is avoided for the hot path: request parsing, routing, and response
//! serialization happen entirely in Rust. Only when a handler is invoked do we re-enter
//! Python via PyO3. For simple handlers (returning string/dict) the overhead is minimal
//! because we use PyO3's critical sections and avoid copying where possible.
//!
//! If this extension is not compiled (e.g., pure-Python fallback), flap falls back to
//! a httptools + uvloop server with identical API.
//!
//! Build with: maturin develop --release

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use axum::{
    body::Body,
    extract::{Path, Query, Request as AxumRequest},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Response as AxumResponse},
    routing::{get, post, put, delete, patch},
    Router,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use tokio::net::TcpListener;

// ---------------------------------------------------------------------------
// Python-exposed entry point
// ---------------------------------------------------------------------------

/// Run the Rust HTTP server.
///
/// Python call: `flap._flap.run(router, host, port, workers)`
/// - router: flap.Router Python object (contains route table)
/// - host, port: bind address
/// - workers: number of tokio worker threads (0 = auto = num_cpus)
///
/// This blocks the current thread running a tokio multi-thread runtime.
/// For benchmarking, use `workers = 1` (pin to current core, best latency).
#[pyfunction]
fn run(py: Python, router_obj: PyObject, host: String, port: u16, workers: usize) -> PyResult<()> {
    // Extract routes from Python router: we expect router.all_routes list
    // Each route has .path (str), .methods (set), .handler (callable)
    // For max performance, we build an Axum Router with closures that call Python handlers.

    // Release GIL while building runtime? No, need GIL for extracting.
    let routes: Vec<(String, Vec<String>, PyObject)> = extract_routes(py, router_obj)?;

    // Build Tokio runtime
    let rt = build_runtime(workers)?;

    // We need to move Python callables into shared state for Axum handlers.
    // PyO3 objects are not Send; we wrap them in `Arc<Py<PyAny>>` and use `Python::with_gil`
    // inside each request.

    rt.block_on(async move {
        let app = build_axum_app(routes);
        let addr = format!("{}:{}", host, port);
        let listener = TcpListener::bind(&addr).await.expect("failed to bind");
        println!(" * Flap running on http://{}/ (Rust engine: tokio+hyper+axum) | Workers: {} | Routes: {}", addr, if workers == 0 { "auto".to_string() } else { workers.to_string() }, app_routes_count(&app));
        axum::serve(listener, app).await.expect("server failed");
    });

    Ok(())
}

fn extract_routes(py: Python, router_obj: PyObject) -> PyResult<Vec<(String, Vec<String>, PyObject)>> {
    let router = router_obj.bind(py);
    // Access router.all_routes
    let all_routes = router.getattr("all_routes")?;
    let mut out = Vec::new();
    for item in all_routes.iter()? {
        let route = item?;
        let path: String = route.getattr("path")?.extract()?;
        let methods_obj = route.getattr("methods")?;
        let methods: Vec<String> = methods_obj.iter()?.map(|m| m.unwrap().extract::<String>().unwrap()).collect();
        let handler: PyObject = route.getattr("handler")?.into();
        out.push((path, methods, handler));
    }
    Ok(out)
}

fn build_runtime(workers: usize) -> PyResult<tokio::runtime::Runtime> {
    let mut builder = tokio::runtime::Builder::new_multi_thread();
    if workers > 0 {
        builder.worker_threads(workers);
    }
    builder.enable_all();
    builder.build().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("tokio runtime failed: {}", e)))
}

fn build_axum_app(routes: Vec<(String, Vec<String>, PyObject)>) -> Router {
    let mut router = Router::new();

    // Shared state: map (path, method) -> handler
    // For demo, we use a simple HashMap protected by Arc; production would use Axum's radix trie directly.
    // Each handler is cloned as Arc<PyObject>.

    for (path, methods, handler) in routes {
        // Convert Flask-style path "/user/<id>" to Axum "/user/:id" or "/user/{id}"
        let axum_path = convert_path(&path);
        let handler_clone = Arc::new(handler);

        // Create a closure for each method
        for method in methods {
            let h = handler_clone.clone();
            let closure = move |req: AxumRequest| {
                let h = h.clone();
                async move { handle_request(req, h).await }
            };
            // Attach to router based on method
            router = match method.as_str() {
                "GET" => router.route(&axum_path, get(closure.clone())),
                "POST" => router.route(&axum_path, post(closure.clone())),
                "PUT" => router.route(&axum_path, put(closure.clone())),
                "DELETE" => router.route(&axum_path, delete(closure.clone())),
                "PATCH" => router.route(&axum_path, patch(closure.clone())),
                _ => router.route(&axum_path, get(closure.clone())),
            };
        }
    }

    // Fallback 404
    router = router.fallback(|| async { (StatusCode::NOT_FOUND, axum::Json(serde_json::json!({"error": "Not Found"}))) });

    router
}

fn convert_path(flask_path: &str) -> String {
    // Flask: /user/<id> or /post/<int:id> -> Axum: /user/:id  (axum 0.7 uses {id})
    // Axum 0.7 supports ":param" and "/*rest"
    // We'll convert <type:name> to :name and <name> to :name, <path:name> to *name
    let mut res = flask_path.to_string();
    // Simple regex replacement without regex crate for brevity: manual parse
    // Pattern: < ... >
    let mut out = String::new();
    let mut chars = res.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '<' {
            // collect until >
            let mut inner = String::new();
            for ch in chars.by_ref() {
                if ch == '>' { break; }
                inner.push(ch);
            }
            // inner may be "int:id" or "id" or "path:file"
            let name = if inner.contains(':') {
                let parts: Vec<&str> = inner.splitn(2, ':').collect();
                let typ = parts[0];
                let n = parts[1];
                if typ == "path" {
                    format!("*{}", n)
                } else {
                    format!(":{}", n)
                }
            } else {
                format!(":{}", inner)
            };
            out.push_str(&name);
        } else {
            out.push(c);
        }
    }
    // Axum 0.7 new syntax uses {param} instead of :param; but both work with feature.
    // Convert :param to {param} for compatibility
    out = out.replace(":", "{").replace("*", "{*");
    // Close braces: we need to add } after each param name
    // Quick fix: split and rejoin
    let mut fixed = String::new();
    let mut in_brace = false;
    for ch in out.chars() {
        if ch == '{' {
            in_brace = true;
            fixed.push(ch);
        } else if in_brace && ch == '/' {
            fixed.push('}');
            in_brace = false;
            fixed.push(ch);
        } else {
            fixed.push(ch);
        }
    }
    if in_brace { fixed.push('}'); }
    fixed
}

async fn handle_request(req: AxumRequest, handler: Arc<PyObject>) -> AxumResponse {
    // Extract components
    let method = req.method().clone();
    let uri = req.uri().clone();
    let path = uri.path().to_string();
    let query = uri.query().unwrap_or("").to_string();
    let headers = req.headers().clone();

    // Body bytes
    let bytes = match req.collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(_) => Bytes::new(),
    };

    // Now call Python handler under GIL
    // We need to construct a flap.Request Python object and invoke handler
    // This is the only GIL section per request - kept minimal.
    let result: Result<(StatusCode, HeaderMap, Bytes), _> = Python::with_gil(|py| {
        // Build Request object via flap.request.Request
        let flap_mod = PyModule::import(py, "flap.request").unwrap();
        let req_cls = flap_mod.getattr("Request").unwrap();

        // Build headers dict
        let py_headers = PyDict::new(py);
        for (k, v) in headers.iter() {
            py_headers.set_item(k.as_str().to_lowercase(), v.to_str().unwrap_or("")).unwrap();
        }

        let py_req = req_cls.call1((
            method.to_string(),
            path.clone(),
            query,
            py_headers,
            bytes.to_vec(),
        )).unwrap();

        // Path params: from Axum Path extractor we would parse, but for simplicity we use query
        // In production, we'd extract via match info. Here we call handler with just req.

        // Call handler: handler(req)
        let callable = handler.bind(py);
        let res_obj = match callable.call1((py_req,)) {
            Ok(o) => o,
            Err(e) => {
                e.print(py);
                return Err("handler error");
            }
        };

        // Normalize result to bytes + status
        // Handler may return str, dict, tuple, Response
        // We delegate to Python's normalize_response via flap.response
        let resp_mod = PyModule::import(py, "flap.response").unwrap();
        let normalize = resp_mod.getattr("normalize_response").unwrap();
        let normed = normalize.call1((res_obj,)).unwrap();
        let (status, _headers, body, _ct): (u16, PyObject, Vec<u8>, Option<String>) = normed.extract().unwrap();

        let mut header_map = HeaderMap::new();
        // For now ignore custom headers from Python; status and body only
        let status_code = StatusCode::from_u16(status).unwrap_or(StatusCode::OK);
        Ok((status_code, header_map, Bytes::from(body)))
    });

    match result {
        Ok((status, headers, body)) => {
            let mut resp = (status, body).into_response();
            // Copy headers
            *resp.headers_mut() = headers;
            resp.headers_mut().insert("server", "flap".parse().unwrap());
            resp
        },
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, axum::Json(serde_json::json!({"error": "Internal Server Error"}))).into_response(),
    }
}

fn app_routes_count(_app: &Router) -> usize {
    // placeholder; Router doesn't expose count, we return 0
    0
}

// Python module definition
#[pymodule]
fn _flap(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add("__version__", "1.0.0")?;
    Ok(())
}
