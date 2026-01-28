FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

# Copier les fichiers
COPY server.py .
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Variables d'environnement
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Port
EXPOSE 8000

# Démarrage
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
