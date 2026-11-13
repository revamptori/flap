import re
import functools
from typing import Callable, Dict, List, Tuple, Optional, Pattern, Any

# Pattern for Flask-style path parameters: <name> , <int:name> , <path:name> , <str:name>
_PARAM_RE = re.compile(r"<(?:(int|str|path):)?([^>]+)>")

_TYPE_PATTERNS = {
    "int": r"(?P<%s>[0-9]+)",
    "str": r"(?P<%s>[^/]+)",
    "path": r"(?P<%s>.+)",
    None: r"(?P<%s>[^/]+)",  # default is str without slash
}

def compile_path(path: str) -> Tuple[Pattern, List[str], Dict[str, str]]:
    """
    Compile a Flask-style path pattern into a regex.
    Returns (regex, param_names, param_types).
    Example: "/user/<int:id>/post/<path:rest>" -> regex with named groups
    """
    param_names: List[str] = []
    param_types: Dict[str, str] = {}
    regex_parts: List[str] = ["^"]
    last = 0
    for m in _PARAM_RE.finditer(path):
        # escape static part
        static = path[last:m.start()]
        regex_parts.append(re.escape(static))
        typ = m.group(1)
        name = m.group(2)
        param_names.append(name)
        if typ:
            param_types[name] = typ
        pattern = _TYPE_PATTERNS.get(typ, _TYPE_PATTERNS[None]) % name
        regex_parts.append(pattern)
        last = m.end()
    # trailing static
    regex_parts.append(re.escape(path[last:]))
    regex_parts.append("$")
    regex_str = "".join(regex_parts)
    compiled = re.compile(regex_str)
    return compiled, param_names, param_types


class Route:
    __slots__ = ("path", "methods", "handler", "cache", "is_dynamic", "regex", "param_names", "param_types", "_prebuilt", "needs_request")
    def __init__(self, path: str, methods: List[str], handler: Callable, cache: bool = False):
        self.path = path
        self.methods = set(m.upper() for m in methods)
        self.handler = handler
        self.cache = cache
        self._prebuilt = None
        # Inspect handler signature to see if it needs Request (fast-path: no Request alloc if handler has 0 args)
        try:
            import inspect
            sig = inspect.signature(handler)
            # handler(req, ...) -> first param is req; if no params, we can skip Request creation for cached static
            self.needs_request = len(sig.parameters) > 0
        except Exception:
            self.needs_request = True
        # detect if dynamic or static
        self.is_dynamic = "<" in path
        if self.is_dynamic:
            self.regex, self.param_names, self.param_types = compile_path(path)
        else:
            self.regex = None
            self.param_names = []
            self.param_types: Dict[str, str] = {}

    def matches(self, method: str, path: str) -> Optional[Dict[str, Any]]:
        if method not in self.methods:
            return None
        if not self.is_dynamic:
            if path == self.path:
                return {}
            return None
        m = self.regex.match(path)  # type: ignore
        if m:
            d = m.groupdict()
            # Convert int params automatically
            for k, typ in self.param_types.items():
                if typ == "int" and k in d:
                    try:
                        d[k] = int(d[k])
                    except ValueError:
                        return None
            return d
        return None


class Router:
    """
    High-performance router with O(1) static lookup + ordered dynamic fallback.
    """
    def __init__(self):
        # static_routes: {(method, path): Route}
        self.static_routes: Dict[Tuple[str, str], Route] = {}
        self.dynamic_routes: List[Route] = []
        # for introspection
        self.all_routes: List[Route] = []
        # Response cache for routes with cache=True (key -> prebuilt http bytes cache)
        # We store normalized tuples to allow keep-alive variation
        self._response_cache: Dict[Tuple, Tuple[int, Dict, bytes, Optional[str]]] = {}
        self._http_cache: Dict[Tuple, bytes] = {}

    def add(self, path: str, methods: List[str], handler: Callable, cache: bool = False):
        route = Route(path, methods, handler, cache=cache)
        self.all_routes.append(route)
        if route.is_dynamic:
            self.dynamic_routes.append(route)
        else:
            for method in route.methods:
                key = (method, route.path)
                if key in self.static_routes:
                    raise ValueError(f"Duplicate route for {method} {route.path}")
                self.static_routes[key] = route
        # Invalidate lru cache when new route added
        try:
            self.match.cache_clear()
            self.match_with_route.cache_clear()
        except AttributeError:
            pass

    @functools.lru_cache(maxsize=2048)
    def match(self, method: str, path: str) -> Tuple[Optional[Callable], Optional[Dict[str, Any]]]:
        # Fast path: static
        key = (method, path)
        route = self.static_routes.get(key)
        if route is not None:
            return route.handler, {}
        # Dynamic fallback - cached via lru_cache for repeated paths like /hello/world
        for route in self.dynamic_routes:
            params = route.matches(method, path)
            if params is not None:
                return route.handler, params
        return None, None

    @functools.lru_cache(maxsize=2048)
    def match_with_route(self, method: str, path: str) -> Tuple[Optional[Callable], Optional[Dict[str, Any]], Optional["Route"]]:
        """Return handler, params, and Route (for cache inspection) - cached"""
        key = (method, path)
        route = self.static_routes.get(key)
        if route is not None:
            return route.handler, {}, route
        for route in self.dynamic_routes:
            params = route.matches(method, path)
            if params is not None:
                return route.handler, params, route
        return None, None, None

    def url_map(self):
        """Debug helper: list all routes"""
        return [(r.path, sorted(r.methods)) for r in self.all_routes]
