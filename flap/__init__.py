"""
flap - A blazing fast Python web framework with a simple Flask-like syntax.

Flap is designed to be at least 5x faster than Flask while keeping an
elegant, minimal API. The performance comes from a Rust-powered HTTP engine
(hyper + axum + tokio) exposed to Python via PyO3. When the Rust extension
is not compiled, a highly-optimized Python fallback using httptools + uvloop
provides the same API with comparable speed.

Example:
    from flap import Flap

    app = Flap()

    @app.get("/")
    def hello(req):
        return "Hello, Flap!"

    @app.get("/user/<id>")
    def get_user(req, id):
        return {"id": id, "name": "Alice"}

    app.run(port=8000)
"""

from .app import Flap
from .request import Request
from .response import Response, jsonify, redirect
from .test_client import TestClient

try:
    # Attempt to load Rust core if compiled (maturin develop)
    from . import _flap  # type: ignore
    _RUST_AVAILABLE = True
except Exception:
    _RUST_AVAILABLE = False

__all__ = ["Flap", "Request", "Response", "jsonify", "redirect", "TestClient", "_RUST_AVAILABLE"]

__version__ = "1.0.0"
__author__ = "flap contributors"
