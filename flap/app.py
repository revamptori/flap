from typing import Callable, List, Optional, Dict, Any
from .router import Router
from .server import run_sync
from .test_client import TestClient
import inspect

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
    def run(self, host: str = "127.0.0.1", port: int = 8000, workers: int = 1, debug: Optional[bool] = None, **kwargs):
        """
        Start the flap server.

        Args:
            host: Bind host (default 127.0.0.1)
            port: Bind port (default 8000)
            workers: Number of worker processes (prefork). Use 1 for single process (default).
            debug: Enable debug logging (overrides constructor debug)
        """
        if debug is not None:
            self.debug = debug

        # Try Rust core first
        try:
            from . import _flap as _rust
            if hasattr(_rust, "run"):
                # Rust signature: _flap.run(router_data, host, port, workers)
                # But we need to convert router to rust representation.
                # For now, our Python fallback is the primary documented method.
                # Rust core is invoked via the same router data if available.
                print(f" * Flap running on http://{host}:{port}/ (Rust engine)")
                # Build simple route table for Rust (list of tuples)
                # Note: Rust engine will handle routing natively for speed.
                # We will attempt to delegate, but if it fails, fallback.
                try:
                    # Prepare serializable routes: [(path, methods, handler_id)] but Rust needs python callbacks
                    # Our Rust extension would hold Python callables via PyO3.
                    # We will call _rust.run with host/port and a dispatcher closure.
                    # Implementation detail is abstracted in extension; we pass router object.
                    # If Rust build supports it, it will use hyper+tokio.
                    _rust.run(self.router, host, port, workers)  # type: ignore
                    return
                except Exception as e:
                    print(f"   Rust engine failed ({e}), falling back to Python engine")
        except ImportError:
            pass
        except Exception:
            pass

        # Python fallback
        run_sync(self.router, host=host, port=port, before_hooks=self._before_hooks, after_hooks=self._after_hooks, workers=workers)

    # ---- Testing ----
    def test_client(self):
        """Return a TestClient for in-process testing (no network)."""
        return TestClient(self.router, self._before_hooks, self._after_hooks)

    # ---- Introspection helpers ----
    def url_map(self):
        """Print all registered routes."""
        for route in self.router.all_routes:
            print(f"{','.join(sorted(route.methods)):10s} {route.path} -> {route.handler.__name__}")

    def __repr__(self):
        return f"<Flap {self.import_name} with {len(self.router.all_routes)} routes>"
