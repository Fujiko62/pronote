# Utiliser une image Python officielle stable
FROM python:3.10-bookworm

# Installer les dépendances système pour Playwright (important !)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copier les fichiers
COPY requirements.txt .
COPY server.py .

# Installer les dépendances Python
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright==1.41.0

# Installer les navigateurs et leurs dépendances
RUN playwright install chromium
RUN playwright install-deps chromium

# Port
EXPOSE 8000

# Démarrage
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
