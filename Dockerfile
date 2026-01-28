FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

COPY requirements.txt .
COPY server.py .

# Installation forcée sans cache
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

EXPOSE 8000

# On utilise python -m gunicorn pour être sûr d'utiliser le bon module
CMD ["python", "-m", "gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
