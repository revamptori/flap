import os
import pytest

def test_engine_auto_defaults_to_rust_if_available():
    import flap
    # auto should resolve to rust if available else python
    engine = flap.get_engine("auto")
    expected = "rust" if flap._RUST_AVAILABLE else "python"
    assert engine == expected

def test_engine_explicit_python(monkeypatch):
    import flap
    monkeypatch.setenv("FLAP_ENGINE", "python")
    assert flap.get_engine() == "python"
    # explicit arg overrides env
    assert flap.get_engine("rust") == "rust"

def test_engine_explicit_rust_without_extension_fails():
    import flap
    from flap import Flap
    # Simulate missing rust by monkeypatching flag
    orig = flap._RUST_AVAILABLE
    try:
        flap._RUST_AVAILABLE = False
        # Also need to patch flap.app's view of it
        import flap.app as app_mod
        # Flap.run should raise if FLAP_ENGINE=rust and rust unavailable
        app = Flap(__name__)
        @app.get("/")
        def h(req): return "hi"
        # Set env to rust
        os.environ["FLAP_ENGINE"] = "rust"
        with pytest.raises(RuntimeError, match="Rust extension not available"):
            app.run(host="127.0.0.1", port=0, workers=1)
    finally:
        flap._RUST_AVAILABLE = orig
        os.environ.pop("FLAP_ENGINE", None)

def test_engine_invalid_value():
    import flap
    with pytest.raises(ValueError):
        flap.get_engine("invalid")

def test_engine_never_silent_fallback(monkeypatch):
    """Ensure FLAP_ENGINE=rust never silently falls back to python."""
    import flap
    # If user selects rust but rust unavailable, it must error, not silently use python
    monkeypatch.setenv("FLAP_ENGINE", "rust")
    orig = flap._RUST_AVAILABLE
    flap._RUST_AVAILABLE = False
    try:
        from flap import Flap
        app = Flap(__name__)
        @app.get("/")
        def h(req): return "hi"
        with pytest.raises(RuntimeError):
            app.run(host="127.0.0.1", port=0)
    finally:
        flap._RUST_AVAILABLE = orig
        monkeypatch.delenv("FLAP_ENGINE", raising=False)

def test_engine_python_explicit_uses_python_even_if_rust_available(monkeypatch):
    import flap
    # If rust is available but user selects python, it should use python
    monkeypatch.setenv("FLAP_ENGINE", "python")
    from flap import Flap
    app = Flap(__name__)
    @app.get("/")
    def h(req): return "hi"
    # We can inspect that run would choose python: patch run_sync to capture
    import flap.server
    captured = {}
    orig = flap.server.run_sync
    def fake_run(*a, **kw):
        captured["called"] = True
        raise KeyboardInterrupt()  # to exit quickly if it does call
    flap.server.run_sync = fake_run
    try:
        try:
            app.run(host="127.0.0.1", port=0)
        except KeyboardInterrupt:
            pass
        assert captured.get("called") is True
    finally:
        flap.server.run_sync = orig
