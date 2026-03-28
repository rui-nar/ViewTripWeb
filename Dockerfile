FROM python:3.11-slim

# Install Node.js (required by Reflex for frontend build)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

# Pre-build the Reflex frontend
RUN reflex export --frontend-only --no-zip 2>/dev/null || true

EXPOSE 3000 8000

CMD ["reflex", "run", "--env", "prod"]
