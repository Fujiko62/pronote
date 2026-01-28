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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message):
    icons = {'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 'success': '✅', 'error': '❌'}
    logger.info(f"{icons.get(step, '📌')} [{step.upper()}] {message}")

def extract_data(html, username):
    data = {
        'studentData': {'name': username.split('@')[0], 'class': '', 'average': None},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'auth_success': True
    }
    try:
        soup = BeautifulSoup(html, 'html.parser')
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0
        
        for span in soup.find_all('span', class_='sr-only'):
            text = span.get_text(' ', strip=True)
            m = re.search(r'de\s+(\d{1,2}h\d{2})\s+à\s+(\d{1,2}h\d{2})\s+(.+)', text, re.I)
            if m and 'pause' not in m.group(3).lower():
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h',':')} - {m.group(2).replace('h',':')}",
                    'subject': m.group(3).strip(),
                    'room': 'Salle'
                })
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p = req.get('username'), req.get('password')
        log_step('start', f"Sync pour {u}")
        
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome','platform': 'windows','mobile': False})
        
        # 1. Accès Pronote
        log_step('auth', f"Accès à {CONFIG['SCHOOL_URL']}")
        r = scraper.get(f"{CONFIG['SCHOOL_URL']}eleve.html")
        
        # 2. Callback
        callback = parse_qs(urlparse(r.url).query).get('callback', [None])[0]
        if not callback:
            m = re.search(r'callback=([^&"\']+)', r.text)
            if m: callback = unquote(m.group(1))
            
        if not callback:
            return jsonify({'error': 'Callback introuvable'}), 401
            
        # 3. Login ENT
        soup = BeautifulSoup(r.text, 'html.parser')
        form = soup.find('form')
        if not form:
            r = scraper.get("https://ent77.seine-et-marne.fr/auth/login")
            soup = BeautifulSoup(r.text, 'html.parser')
            form = soup.find('form')
            
        action = form.get('action')
        if not action.startswith('http'): action = urljoin(r.url, action)
            
        data = {i['name']: i.get('value', '') for i in form.find_all('input') if i.get('name')}
        data['email'] = u
        data['password'] = p
        
        log_step('auth', "Envoi login...")
        r = scraper.post(action, data=data)
        
        if 'auth/login' in r.url:
            return jsonify({'error': 'Identifiants incorrects', 'auth_success': False}), 401
            
        # 4. Retour Pronote
        log_step('redirect', "Retour Pronote...")
        r = scraper.get(unquote(callback))
        
        result = extract_data(r.text, u)
        log_step('success', "Terminé !")
        return jsonify(result)
        
    except Exception as e:
        log_step('error', str(e))
        return jsonify({'error': str(e), 'auth_success': False}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '5.0-cloudscraper'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
