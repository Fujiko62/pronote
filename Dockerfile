FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

# Copier les fichiers
COPY requirements.txt .
COPY server.py .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Installer Playwright browsers
RUN playwright install chromium

# Port exposé
EXPOSE 10000

# Commande de démarrage
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1"]
