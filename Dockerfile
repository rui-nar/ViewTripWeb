FROM python:3.11-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.router:app", "--host", "0.0.0.0", "--port", "8000"]
