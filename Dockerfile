FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

# 1. Copier les fichiers
COPY requirements.txt .
COPY server.py .

# 2. Créer un environnement virtuel (C'est le secret !)
RUN python -m venv /opt/venv
# 3. Activer l'environnement pour toutes les commandes suivantes
ENV PATH="/opt/venv/bin:$PATH"

# 4. Installer les dépendances DANS l'environnement virtuel
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright==1.41.0

# 5. Installer Chrome
RUN playwright install chromium

# 6. Configuration
EXPOSE 8000

# 7. Démarrer le serveur via l'environnement virtuel
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
