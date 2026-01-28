FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

# Copier les fichiers
COPY server.py .
COPY requirements.txt .

# Installer les dépendances dans le système global
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright==1.41.0

# Installer les navigateurs Playwright
RUN playwright install chromium

# Variables d'environnement pour Python
ENV PYTHONPATH=/usr/local/lib/python3.10/site-packages
ENV PATH="/usr/local/bin:${PATH}"

EXPOSE 8000

# Démarrage avec le chemin complet de gunicorn
CMD ["/usr/local/bin/gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
