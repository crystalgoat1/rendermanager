FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (file is in project root)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy server package
COPY server/ ./server/

EXPOSE 8000

CMD ["uvicorn", "server.server_main:app", "--host", "0.0.0.0", "--port", "8000"]
