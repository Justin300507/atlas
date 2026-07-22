import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/items")
def list_items():
    return []


class ItemService:
    def get(self):
        return None
