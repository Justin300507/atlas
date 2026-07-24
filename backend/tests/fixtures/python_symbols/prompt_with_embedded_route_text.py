BACKEND_PROMPT = """
You are generating a FastAPI backend. Follow this example:

@app.get("/users")
def list_users():
    return []
"""


def build_prompt() -> str:
    return BACKEND_PROMPT
