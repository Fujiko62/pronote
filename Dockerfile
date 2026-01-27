FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

COPY requirements.txt .
COPY server.py .

RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

EXPOSE 10000

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1"]
