# BD-42 backend — FastAPI + uvicorn
FROM python:3.12-slim

WORKDIR /app

# Dependencies first: this layer is cached unless requirements.txt changes,
# so code edits don't trigger a full reinstall.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (see .dockerignore for what's excluded)
COPY . .

EXPOSE 8000

# --reload for dev; docker-compose mounts the source as a volume so edits
# on the host are picked up live. For production this would drop --reload.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
