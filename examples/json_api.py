"""JSON API example with all HTTP methods"""
from flap import Flap

app = Flap(__name__)

# In-memory DB for demo
db = {}
_next_id = 1

@app.get("/")
def index(req):
    return {"message": "Welcome to flap JSON API", "endpoints": ["/users", "/users/<id>"]}

@app.get("/users")
def list_users(req):
    return list(db.values())

@app.get("/users/<id>")
def get_user(req, id):
    user = db.get(id)
    if not user:
        return {"error": "not found"}, 404
    return user

@app.post("/users")
def create(req):
    global _next_id
    data = req.json()
    if not data or "name" not in data:
        return {"error": "name required"}, 400
    uid = str(_next_id)
    _next_id += 1
    user = {"id": uid, "name": data["name"]}
    db[uid] = user
    return user, 201

@app.put("/users/<id>")
def update(req, id):
    if id not in db:
        return {"error": "not found"}, 404
    data = req.json()
    db[id].update(data)
    return db[id]

@app.delete("/users/<id>")
def delete(req, id):
    db.pop(id, None)
    return "", 204

@app.get("/search")
def search(req):
    q = req.query.get("q", "")
    return {"q": q, "results": [u for u in db.values() if q.lower() in u["name"].lower()]}

if __name__ == "__main__":
    print("Try:")
    print("  curl http://localhost:8000/users")
    print("  curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' -d '{\"name\":\"Ada\"}'")
    app.run(port=8000)
