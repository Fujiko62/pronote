FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

COPY requirements.txt .
COPY server.py .

# Créer un environnement virtuel
RUN python -m venv /opt/venv
# Activer l'environnement virtuel pour toutes les commandes suivantes
ENV PATH="/opt/venv/bin:$PATH"

# Installer les dépendances DANS l'environnement virtuel
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright==1.41.0

# Installer les navigateurs Playwright
RUN playwright install chromium

EXPOSE 8000

# Démarrer avec gunicorn DEPUIS l'environnement virtuel
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
