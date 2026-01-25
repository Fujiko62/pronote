from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import logging
import re
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def login_and_scrape(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    try:
        # 1. Login CAS (comme avant, ca marche)
        resp = session.get(pronote_url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        if not form: return None
        
        action = form.get('action')
        if action.startswith('/'):
            parsed = urlparse(resp.url)
            action = f"{parsed.scheme}://{parsed.netloc}{action}"
            
        parsed_orig = urlparse(resp.url)
        callback = parse_qs(parsed_orig.query).get('callback', [''])[0]
        if callback and '?' not in action: action += f"?callback={callback}"
        
        user_field = 'username' if soup.find('input', {'name': 'username'}) else 'email'
        pass_field = 'password'
        
        resp2 = session.post(
            action, 
            data={user_field: username, pass_field: password},
            headers={'Referer': resp.url}
        )
        
        if 'pronote' not in resp2.url.lower():
            return None
            
        # 2. ON EST CONNECTE ! ANALYSONS LA PAGE D'ACCUEIL
        # Pronote charge souvent les donnees via un gros JSON dans la page
        html = resp2.text
        soup = BeautifulSoup(html, 'html.parser')
        
        data = {
            'studentData': {'name': username, 'class': 'Non detectee', 'average': 0},
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': []
        }
        
        # --- ESSAI 1: Trouver le nom dans le titre ou header ---
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title:
            # Parfois le titre est "PRONOTE - Nom Prenom - Espace Eleve"
            parts = title.split('-')
            if len(parts) > 1:
                possible_name = parts[1].strip()
                if "Espace" not in possible_name:
                    data['studentData']['name'] = possible_name
        
        # --- ESSAI 2: Chercher les donnees JSON cachees ---
        # Pronote stocke souvent les donnees dans une variable JS "donnees" ou "G"
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string: continue
            
            # Chercher le nom
            if 'Nom' in script.string and 'Prenom' in script.string:
                # Regex un peu sauvage pour trouver des objets JSON
                name_match = re.search(r"Nom['\"]?:\s*['\"]([^'\"]+)['\"]", script.string)
                if name_match:
                    data['studentData']['name'] = name_match.group(1)
            
            # Chercher la classe
            class_match = re.search(r"Classe['\"]?:\s*['\"]([^'\"]+)['\"]", script.string)
            if class_match:
                data['studentData']['class'] = class_match.group(1)

        # --- ESSAI 3: Simuler des devoirs si on ne trouve rien ---
        # Si on est connecte mais qu'on ne peut pas lire (chiffrement),
        # on renvoie au moins le statut connecte avec le bon nom
        
        return data

    except Exception as e:
        logger.error(f"Scraping error: {e}")
        return None

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        data_scraped = login_and_scrape(
            data.get('username'), 
            data.get('password'), 
            data.get('schoolUrl') + 'eleve.html'
        )
        
        if data_scraped:
            return jsonify(data_scraped)
        else:
            return jsonify({'error': 'Echec connexion'}), 401
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
