# Utiliser une image Python officielle très stable (Debian 12)
FROM python:3.10-bookworm

# Installer les outils nécessaires
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copier les fichiers
COPY requirements.txt .
COPY server.py .

# Créer un environnement virtuel
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Installer les dépendances Python
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright==1.41.0

# Installer les navigateurs Playwright + dépendances système
RUN playwright install chromium
RUN playwright install-deps chromium

EXPOSE 8000

# Lancer le serveur
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
