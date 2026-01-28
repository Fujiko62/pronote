FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

COPY server.py .

RUN pip install --no-cache-dir Flask==3.0.0 flask-cors==4.0.0 gunicorn==21.2.0
RUN playwright install chromium

EXPOSE 8000

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
