import os
import re
import json
import logging
import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import urlparse, parse_qs, unquote, urljoin

app = Flask(__name__)
CORS(app)

# Logs détaillés
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
logger = logging.getLogger(__name__)

# Configuration hardcodée
CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message):
    icons = {'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 'success': '✅', 'error': '❌', 'info': 'ℹ️'}
    logger.info(f"{icons.get(step, '📌')} [{step.upper()}] {message}")

def extract_data(html, username, url):
    """Extrait les données de la page Pronote"""
    data = {
        'studentData': {'name': username.split('@')[0].replace('.', ' ').title(), 'class': '', 'average': None},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'auth_success': False,
        'raw_found': []
    }
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else ""
        data['raw_found'].append(f"Titre: {title}")
        data['raw_found'].append(f"URL: {url}")
        data['raw_found'].append(f"Taille: {len(html)} bytes")
        
        # Vérifier si on est sur Pronote
        if 'pronote' in url.lower() or 'index-education' in url.lower():
            data['auth_success'] = True
            
            # Nom depuis le titre
            if title and '-' in title:
                for part in title.split('-'):
                    clean = part.strip().replace('ESPACE ÉLÈVE', '').replace('PRONOTE', '').strip()
                    if clean and len(clean) > 2:
                        data['studentData']['name'] = clean
                        break
            
            # Classe
            match = re.search(r'(\d+)(?:ème|EME|e|è)\s*([A-Z0-9])?', html, re.I)
            if match:
                data['studentData']['class'] = match.group(0).upper()
            
            # Emploi du temps (sr-only)
            day_idx = datetime.datetime.now().weekday()
            if day_idx > 4: day_idx = 0
            
            for span in soup.find_all('span', class_='sr-only'):
                text = span.get_text(' ', strip=True)
                match = re.search(r'de\s+(\d{1,2}h\d{2})\s+à\s+(\d{1,2}h\d{2})\s+(.+)', text, re.I)
                if match:
                    subject = match.group(3).strip()
                    if 'pause' not in subject.lower():
                        data['schedule'][day_idx].append({
                            'time': f"{match.group(1).replace('h',':')} - {match.group(2).replace('h',':')}",
                            'subject': subject,
                            'teacher': '',
                            'room': 'Salle'
                        })
                        data['raw_found'].append(f"Cours: {subject}")
    except Exception as e:
        data['raw_found'].append(f"Erreur: {str(e)}")
    
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        username = req.get('username', '')
        password = req.get('password', '')
        
        log_step('start', "=" * 50)
        log_step('start', "NOUVELLE SYNCHRONISATION")
        log_step('start', "=" * 50)
        log_step('info', f"Utilisateur: {username[:20]}***")
        
        if not username or not password:
            return jsonify({'error': 'Identifiants requis', 'auth_success': False}), 400
        
        # Session HTTP
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        })
        
        # Étape 1: Aller sur Pronote
        log_step('auth', f"Accès à {CONFIG['SCHOOL_URL']}eleve.html")
        resp = session.get(f"{CONFIG['SCHOOL_URL']}eleve.html", allow_redirects=True, timeout=30)
        log_step('redirect', f"Redirigé vers: {resp.url[:60]}...")
        
        # Étape 2: Récupérer le callback
        callback = parse_qs(urlparse(resp.url).query).get('callback', [None])[0]
        if callback:
            callback = unquote(callback)
            log_step('success', "Callback trouvé!")
        
        # Étape 3: Trouver le formulaire de login
        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        
        if form:
            action = form.get('action', '')
            if action and not action.startswith('http'):
                action = urljoin(resp.url, action)
            elif not action:
                action = resp.url
            
            # Collecter les champs
            form_data = {}
            for inp in form.find_all('input', type='hidden'):
                if inp.get('name'):
                    form_data[inp.get('name')] = inp.get('value', '')
            
            # Ajouter identifiants
            form_data['email'] = username
            form_data['password'] = password
            
            log_step('auth', f"Envoi login à: {action[:50]}...")
            login_resp = session.post(action, data=form_data, allow_redirects=True, timeout=30)
            log_step('redirect', f"URL après login: {login_resp.url[:60]}...")
            
            # Vérifier échec
            if 'login' in login_resp.url.lower() and 'error' in login_resp.url.lower():
                log_step('error', "Identifiants incorrects!")
                return jsonify({'error': 'Identifiants incorrects', 'auth_success': False}), 401
            
            log_step('success', "Login OK!")
            
            # Étape 4: Aller sur Pronote
            if 'pronote' in login_resp.url.lower() or 'index-education' in login_resp.url.lower():
                final_resp = login_resp
            elif callback:
                log_step('redirect', "Suivi du callback...")
                final_resp = session.get(callback, allow_redirects=True, timeout=30)
            else:
                final_resp = session.get(f"{CONFIG['SCHOOL_URL']}eleve.html", allow_redirects=True, timeout=30)
            
            log_step('info', f"URL finale: {final_resp.url[:60]}...")
            
            # Étape 5: Extraire les données
            log_step('extract', "Extraction des données...")
            result = extract_data(final_resp.text, username, final_resp.url)
            
            log_step('success', "=" * 50)
            log_step('info', f"Auth: {'✅' if result['auth_success'] else '❌'}")
            log_step('info', f"Élève: {result['studentData']['name']}")
            log_step('info', f"Cours: {sum(len(d) for d in result['schedule'])}")
            log_step('success', "=" * 50)
            
            return jsonify(result)
        else:
            log_step('error', "Formulaire non trouvé!")
            return jsonify({'error': 'Formulaire login introuvable', 'auth_success': False}), 401
            
    except Exception as e:
        log_step('error', f"Erreur: {str(e)}")
        return jsonify({'error': str(e), 'auth_success': False}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '2.0', 'school': CONFIG['SCHOOL_NAME']})

@app.route('/')
def home():
    return jsonify({'name': 'Pronote Bridge', 'status': 'running 🚀'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
