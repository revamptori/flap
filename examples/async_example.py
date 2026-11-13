"""Async handler example (non-blocking)"""
import asyncio
from flap import Flap

app = Flap(__name__)

@app.get("/")
def home(req):
    return {"msg": "sync handler"}

@app.get("/async")
async def async_hello(req):
    # Simulate I/O without blocking the event loop
    await asyncio.sleep(0.05)
    return {"msg": "async hello", "slept": "50ms"}

@app.get("/sync-slow")
def sync_slow(req):
    # Blocking sleep would stall the server - use async instead!
    # But for demo, small blocking:
    import time
    time.sleep(0.01)
    return {"msg": "sync slow (blocking)"}

if __name__ == "__main__":
    print("Visit http://localhost:8000/async (async) vs /sync-slow (blocking)")
    app.run(port=8000)
