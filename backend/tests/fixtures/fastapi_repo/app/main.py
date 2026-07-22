from fastapi import FastAPI

app = FastAPI()


@app.get("/users")
def list_users():
    return []


@app.post("/users")
def create_user():
    return {}
