import argparse
import importlib.util
import sys

def main():
    parser = argparse.ArgumentParser(prog="flap", description="flap web framework CLI")
    parser.add_argument("app", nargs="?", help="Python file containing app (e.g., app.py:app)")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    parser.add_argument("--workers", type=int, default=1, help="number of workers")
    args = parser.parse_args()

    if not args.app:
        parser.print_help()
        print("\nExample: flap examples/hello.py --port 8000")
        return

    # Handle file:object or file
    if ":" in args.app:
        path, obj_name = args.app.split(":", 1)
    else:
        path, obj_name = args.app, "app"

    spec = importlib.util.spec_from_file_location("user_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = getattr(mod, obj_name)
    app.run(host=args.host, port=args.port, workers=args.workers)

if __name__ == "__main__":
    main()
