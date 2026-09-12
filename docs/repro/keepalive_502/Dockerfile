FROM caddy:2 AS caddy
FROM python:3.14-slim
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
RUN pip install --no-cache-dir "fastapi==0.141.1" "uvicorn==0.52.4" "h11==0.16.0"
WORKDIR /r
COPY app.py Caddyfile relay.py driver.py run.sh ./
RUN chmod +x run.sh && sed -i 's/\r$//' run.sh app.py relay.py driver.py Caddyfile
ENTRYPOINT ["/r/run.sh"]
