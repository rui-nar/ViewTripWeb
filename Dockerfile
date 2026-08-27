FROM python:3.14-slim

# Build-time version (the git tag), exposed at runtime so /api/version can report
# it and the web client can detect a stale cached bundle. Defaults to "dev".
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run migrations then start the server
COPY entrypoint.sh /entrypoint.sh
# One image, two roles (issue #173): the default CMD serves the API; the worker
# service overrides it with /worker-entrypoint.sh. Same code, same deploy.
COPY worker-entrypoint.sh /worker-entrypoint.sh
RUN chmod +x /entrypoint.sh /worker-entrypoint.sh
CMD ["/entrypoint.sh"]
