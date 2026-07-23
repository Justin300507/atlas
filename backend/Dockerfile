# python:3.12, not latest -- tree-sitter-languages has no wheels for newer
# Python yet (same constraint the local dev venv is pinned to).
FROM python:3.12-slim

# git is required at runtime: cloner.py shells out to the git CLI to clone
# the repos Atlas analyzes.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
