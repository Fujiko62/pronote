import os
import re
import logging
import datetime
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import urlparse, parse_qs, unquote, urljoin

app = Flask(__name__)
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message):
    icons = {'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 'success': '✅', 'error': '❌', 'info': 'ℹ️'}
    logger.info(f"{icons.get(step, '📌')} [{step.upper()}] {message}")

def extract_data(html, username):
    """Extrait les données de la page HTML"""
    data = {
        'studentData': {'name': username.split('@')[0].replace('.', ' ').title(), 'class': '', 'average': None},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'auth_success': True,
        'raw_found': []
    }
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Nom depuis le titre
        title = soup.title.string if soup.title else ""
        if title and '-' in title:
            clean = title.split('-')[1].replace('ESPACE ÉLÈVE', '').strip()
            if len(clean) > 2:
                data['studentData']['name'] = clean
                log_step('success', f"Nom trouvé: {clean}")

        # Classe
        match = re.search(r'(\d+)(?:ème|EME|e|è)\s*([A-Z0-9])?', html, re.I)
        if match:
            data['studentData']['class'] = match.group(0).upper()
            log_step('success', f"Classe trouvée: {data['studentData']['class']}")

        # Emploi du temps (sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0
        
        count = 0
        for span in soup.find_all('span', class_='sr-only'):
            text = span.get_text(' ', strip=True)
            m = re.search(r'de\s+(\d{1,2}h\d{2})\s+à\s+(\d{1,2}h\d{2})\s+(.+)', text, re.I)
            if m and 'pause' not in m.group(3).lower():
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h',':')} - {m.group(2).replace('h',':')}",
                    'subject': m.group(3).strip(),
                    'teacher': '',
                    'room': 'Salle'
                })
                count += 1
        log_step('info', f"Cours trouvés: {count}")
                
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p = req.get('username'), req.get('password')
        
        log_step('start', f"Sync pour {u.split('@')[0]}***")
        
        # CloudScraper simule un vrai navigateur Chrome
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
        
        # 1. Accès Pronote (redirige vers ENT)
        log_step('auth', f"Accès à {CONFIG['SCHOOL_URL']}eleve.html")
        r = scraper.get(f"{CONFIG['SCHOOL_URL']}eleve.html")
        log_step('redirect', f"Redirigé vers: {r.url[:60]}...")
        
        # 2. Callback (CAS)
        callback = parse_qs(urlparse(r.url).query).get('callback', [None])[0]
        if not callback:
            m = re.search(r'callback=([^&"\']+)', r.text)
            if m: callback = unquote(m.group(1))
            
        if not callback:
            log_step('error', "Callback CAS introuvable")
            return jsonify({'error': 'Callback introuvable'}), 401
            
        log_step('success', "Callback trouvé")
        
        # 3. Login ENT (ent77)
        soup = BeautifulSoup(r.text, 'html.parser')
        form = soup.find('form')
        
        if not form:
            # Essayer d'aller directement sur le login
            log_step('auth', "Formulaire non trouvé, tentative directe...")
            r = scraper.get("https://ent77.seine-et-marne.fr/auth/login")
            soup = BeautifulSoup(r.text, 'html.parser')
            form = soup.find('form')
            
        if not form:
            log_step('error', "Formulaire login introuvable")
            return jsonify({'error': 'Formulaire login introuvable'}), 401
            
        action = form.get('action')
        if not action.startswith('http'):
            action = urljoin(r.url, action)
        elif not action:
            action = r.url
            
        # Collecter les champs
        data = {}
        for i in form.find_all('input'):
            if i.get('name'):
                data[i.get('name')] = i.get('value', '')
                
        # Trouver les champs email/password
        email_field = 'email'
        if form.find('input', {'name': 'username'}): email_field = 'username'
        
        password_field = 'password'
        if form.find('input', {'name': 'password'}): password_field = 'password'
        
        data[email_field] = u
        data[password_field] = p
        
        log_step('auth', f"Envoi login à {action[:50]}...")
        r = scraper.post(action, data=data)
        
        if 'auth/login' in r.url or 'error' in r.url:
            log_step('error', "Login échoué (mauvais mot de passe ?)")
            return jsonify({'error': 'Identifiants incorrects', 'auth_success': False}), 401
            
        log_step('success', "Login ENT réussi !")
        
        # 4. Retour Pronote via Callback
        log_step('redirect', "Retour vers Pronote...")
        r = scraper.get(unquote(callback))
        log_step('info', f"URL finale: {r.url[:60]}...")
        
        # 5. Extraction
        result = extract_data(r.text, u)
        
        log_step('success', "Extraction terminée")
        return jsonify(result)
        
    except Exception as e:
        log_step('error', str(e))
        return jsonify({'error': str(e), 'auth_success': False}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '4.0-cloudscraper', 'school': CONFIG['SCHOOL_NAME']})

@app.route('/')
def home():
    return jsonify({'name': 'Pronote Bridge', 'status': 'running 🚀'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
