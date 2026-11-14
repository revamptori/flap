"""
flap - A blazing fast Python web framework with a simple Flask-like syntax.

Flap uses a Rust-powered HTTP engine (hyper + axum + tokio) by default,
exposed via PyO3. A pure-Python fallback (httptools + uvloop) is available
via FLAP_ENGINE=python for environments without the Rust extension.

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
# 1:1 Flask compat: Flask alias and globals
from .app import Flask  # alias, see app.py
try:
    from .globals import request, g, session, set_request_ctx, reset_request_ctx
except ImportError:
    request = None  # type: ignore
    g = None  # type: ignore
    session = {}  # type: ignore
    set_request_ctx = lambda req: (None, None)  # type: ignore
    reset_request_ctx = lambda tok: None  # type: ignore
from .response import abort, make_response, url_for  # Flask compat

try:
    # Attempt to load Rust core if compiled (maturin develop --release)
    from . import _flap  # type: ignore
    _RUST_AVAILABLE = True
except Exception:
    _RUST_AVAILABLE = False
    _flap = None  # type: ignore

import os as _os

def _resolve_engine(explicit: str | None = None) -> str:
    """
    Resolve which engine to use.
    Priority: explicit arg > FLAP_ENGINE env var > auto (rust if available else python).
    Returns "rust" or "python".
    Never silently falls back — caller must enforce.
    """
    raw = explicit if explicit is not None else _os.getenv("FLAP_ENGINE", "auto")
    raw = raw.strip().lower() if isinstance(raw, str) else "auto"
    if not raw:
        raw = "auto"
    if raw not in ("auto", "rust", "python"):
        raise ValueError(f"Invalid FLAP_ENGINE value {raw!r} (expected 'rust', 'python', or 'auto')")
    if raw == "auto":
        return "rust" if _RUST_AVAILABLE else "python"
    return raw

def get_engine(explicit: str | None = None) -> str:
    """Public helper: return resolved engine name without side effects."""
    return _resolve_engine(explicit)

def is_rust_available() -> bool:
    return _RUST_AVAILABLE

__all__ = ["Flap", "Flask", "Request", "Response", "jsonify", "redirect", "abort", "make_response", "url_for", "request", "g", "session", "TestClient", "_RUST_AVAILABLE", "get_engine", "is_rust_available"]

__version__ = "1.0.0"
__author__ = "flap contributors"
