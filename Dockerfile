# On part de l'image officielle Microsoft qui contient DÉJÀ tout !
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# On définit le dossier de travail
WORKDIR /app

# On installe juste Flask et gunicorn
RUN pip install Flask==3.0.0 flask-cors==4.0.0 gunicorn==21.2.0

# On copie ton script
COPY server.py .

# On expose le port 8000
EXPOSE 8000

# On lance le serveur
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--timeout", "120", "--workers", "1"]
