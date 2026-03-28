FROM python:3.11-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .
# web_client/ is built by deploy.ps1 (flutter build web) before docker build
COPY web_client/ /app/web_client/

EXPOSE 8000

# Run migrations then start the server
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
