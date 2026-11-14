from typing import Callable, List, Optional, Dict, Any
from .router import Router
from .test_client import TestClient
import inspect
import os

class Flap:
    """
    Flap - a Flask-inspired but faster web framework.

    Syntax was chosen to be minimal and familiar to Flask/FastAPI users:

        from flap import Flap

        app = Flap(__name__)

        @app.get("/")
        def home(req):
            return "Hello, World!"

        @app.get("/user/<id>")
        def get_user(req, id):
            return {"id": id}

        @app.post("/echo")
        def echo(req):
            return req.json()

        app.run(port=8000)

    Decorators:
        @app.route(path, methods=[...])
        @app.get(path)  @app.post(path)  @app.put(path)  @app.delete(path)  @app.patch(path)

    Handler signature:
        def handler(req, <path_param1>, <path_param2>, ...):
            # req is flap.Request
            # path params are injected as kwargs (strings; <int:..> still string, convert if needed)
            # return types: str | dict | list | bytes | Response | (body, status) | (body, status, headers)
            return ...

    Hooks:
        @app.before_request
        def before(req): ...

        @app.after_request
        def after(req, status, headers, body): ...

    Engine selection:
        FLAP_ENGINE env var controls execution engine:
            FLAP_ENGINE=rust   -> require Rust (hyper+tokio), fail if unavailable (never silent fallback)
            FLAP_ENGINE=python -> use Python fallback (httptools+uvloop)
            FLAP_ENGINE=auto   -> default: Rust if compiled else Python (default is Rust-first)
        app.run(engine="rust"/"python") can override env var.
    """

    def __init__(self, import_name: str = __name__, debug: bool = False):
        self.import_name = import_name
        self.debug = debug
        self.router = Router()
        self._before_hooks: List[Callable] = []
        self._after_hooks: List[Callable] = []
        # For compatibility with Flask-style config
        self.config: Dict[str, Any] = {"DEBUG": debug}

    # ---- Routing decorators ----
    def route(self, path: str, methods: Optional[List[str]] = None, cache: bool = False):
        if methods is None:
            methods = ["GET"]
        # Normalize methods to uppercase
        methods = [m.upper() for m in methods]

        def decorator(fn: Callable):
            self.router.add(path, methods, fn, cache=cache)
            return fn
        return decorator

    # Sugar methods
    def get(self, path: str, cache: bool = False):
        return self.route(path, methods=["GET"], cache=cache)

    def post(self, path: str, cache: bool = False):
        return self.route(path, methods=["POST"], cache=cache)

    def put(self, path: str, cache: bool = False):
        return self.route(path, methods=["PUT"], cache=cache)

    def delete(self, path: str, cache: bool = False):
        return self.route(path, methods=["DELETE"], cache=cache)

    def patch(self, path: str, cache: bool = False):
        return self.route(path, methods=["PATCH"], cache=cache)

    # Alias for Flask compatibility: @app.route with methods param covers all
    # But also allow app.add_url_rule style if someone wants
    def add_url_rule(self, path: str, endpoint: Optional[str] = None, view_func: Optional[Callable] = None, methods: Optional[List[str]] = None):
        """Flask-compatible alias for router.add"""
        if view_func is None:
            raise ValueError("view_func is required")
        self.router.add(path, methods or ["GET"], view_func)

    # ---- Hooks ----
    def before_request(self, fn: Callable):
        """Register a function to run before each request. If it returns a response, handler is skipped."""
        self._before_hooks.append(fn)
        return fn

    def after_request(self, fn: Callable):
        """Register a function to run after each request. Can modify (status, headers, body)."""
        self._after_hooks.append(fn)
        return fn

    # ---- Running ----
    def run(self, host: str = "127.0.0.1", port: int = 8000, workers: int = 1, debug: Optional[bool] = None, engine: Optional[str] = None, **kwargs):
        """
        Start the flap server.

        Args:
            host: Bind host (default 127.0.0.1)
            port: Bind port (default 8000)
            workers: Number of worker processes (prefork). Use 1 for single process (default).
            debug: Enable debug logging (overrides constructor debug)
            engine: Execution engine override: "rust", "python", or None (use FLAP_ENGINE env var, default Rust)
                    Never silently falls back — if selected engine is unavailable, raises.
        """
        if debug is not None:
            self.debug = debug

        # Resolve engine: explicit arg > FLAP_ENGINE env var > auto (rust default)
        from . import _RUST_AVAILABLE, _resolve_engine

        # _resolve_engine handles ValueError for invalid values
        resolved = _resolve_engine(engine)

        if resolved == "rust":
            if not _RUST_AVAILABLE:
                raise RuntimeError(
                    "FLAP_ENGINE=rust selected but Rust extension not available. "
                    "Build with `maturin develop --release` or set FLAP_ENGINE=python to use Python fallback."
                )
            # Use Rust engine - never silent fallback
            from . import _flap as _rust
            if not hasattr(_rust, "run"):
                raise RuntimeError("Rust extension present but missing `run` entrypoint")
            print(f" * Flap running on http://{host}:{port}/ (Rust engine: tokio+hyper+axum) | Workers: {workers} | Routes: {len(self.router.all_routes)}")
            # Pass entire app (router + hooks) so Rust can handle middleware correctly.
            # Backwards compat: _rust.run historically accepted router; now we pass app.
            # Rust extractor detects both shapes.
            _rust.run(self, host, port, workers)  # type: ignore
            return

        # Python fallback (explicit or auto when Rust unavailable)
        if resolved == "python" and _RUST_AVAILABLE and engine is None:
            # User explicitly requested python via env var - respect it and log
            pass

        from .server import run_sync
        run_sync(self.router, host=host, port=port, before_hooks=self._before_hooks, after_hooks=self._after_hooks, workers=workers)

    # ---- Testing ----
    def test_client(self, engine: Optional[str] = None):
        """Return a TestClient for in-process testing (no network).
        Engine param is accepted for symmetry but test client always uses Python Router logic
        so behavior is comparable across engines. Use `FLAP_ENGINE` to test server engines.
        """
        return TestClient(self.router, self._before_hooks, self._after_hooks)

    # ---- Introspection helpers ----
    def url_map(self):
        """Print all registered routes."""
        for route in self.router.all_routes:
            print(f"{','.join(sorted(route.methods)):10s} {route.path} -> {route.handler.__name__}")

    def __repr__(self):
        return f"<Flap {self.import_name} with {len(self.router.all_routes)} routes>"
