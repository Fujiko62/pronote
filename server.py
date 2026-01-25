from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import pronotepy.cryptography
import pronotepy.pronoteAPI
import pronotepy.dataClasses
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re
import socket
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CLIENT PRONOTE CUSTOM ---

class CustomClient(pronotepy.Client):
    """Client qui accepte une session deja ouverte"""
    def __init__(self, pronote_url, session_params):
        self.pronote_url = pronote_url
        self.session_id = session_params['h']
        self.username = session_params['e']
        self.password = session_params['f']
        self.attributes = {'a': session_params.get('a', 3)}
        
        # Initialiser la session requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Initialiser chiffrement
        self.encryption = pronotepy.cryptography.Crypter(self.session_id)
        
        # Parametres
        self.communication = pronotepy.pronoteAPI.Communication(self.pronote_url, self.attributes, self.encryption, self.session)
        
        # Obtenir les options et periode
        self.func_options = self.communication.post('FonctionParametres', {'donnees': {'Uuid': self.encryption.uuid}})
        
        # On considere qu'on est deja loggue
        self.logged_in = True
        self.calculated_username = "Utilisateur" # Placeholder
        
        # Recuperer les infos utilisateur
        self.user_data = self.communication.post('ParametresUtilisateur', {})
        if self.user_data and 'donnees' in self.user_data:
            self.info = pronotepy.dataClasses.User(self.user_data['donnees']['ressource'])
            
            # Periodes
            if 'donnees' in self.func_options and 'listePeriodes' in self.func_options['donnees']:
                self.periods = [pronotepy.dataClasses.Period(p) for p in self.func_options['donnees']['listePeriodes']]
                self.current_period = next((p for p in self.periods if p.is_current), self.periods[0] if self.periods else None)
            else:
                self.periods = []
                self.current_period = None

# --- SCRAPING CAS ---

def login_cas_scraping(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    logger.info("--- Debut Scraping ---")
    
    try:
        # 1. Acces Pronote
        resp = session.get(pronote_url, allow_redirects=True, timeout=10)
        
        # Si on est redirige vers l'ENT
        if 'ent' in resp.url:
            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            
            if form:
                action = form.get('action', '')
                
                # Gerer l'URL d'action relative
                if action.startswith('/'):
                    parsed = urlparse(resp.url)
                    action = f"{parsed.scheme}://{parsed.netloc}{action}"
                
                # Garder le callback
                parsed_orig = urlparse(resp.url)
                callback = parse_qs(parsed_orig.query).get('callback', [''])[0]
                if callback and '?' not in action:
                    action += f"?callback={callback}"
                
                # Chercher les noms des champs
                user_field = 'email'
                pass_field = 'password'
                
                if soup.find('input', {'name': 'username'}): user_field = 'username'
                if soup.find('input', {'name': 'login'}): user_field = 'login'
                
                # POST
                data = {user_field: username, pass_field: password}
                resp2 = session.post(action, data=data, allow_redirects=True, headers={'Referer': resp.url})
                
                # 3. Extraction Session Pronote
                if 'pronote' in resp2.url.lower():
                    soup2 = BeautifulSoup(resp2.text, 'html.parser')
                    body = soup2.find('body')
                    if body and body.get('onload'):
                        onload = body.get('onload')
                        match = re.search(r"Start\s*\(\s*\{([^}]+)\}", onload)
                        if match:
                            params = match.group(1)
                            h = re.search(r"h[:\s]*['\"]?(\d+)", params)
                            e = re.search(r"e[:\s]*['\"]([^'\"]+)['\"]", params)
                            f = re.search(r"f[:\s]*['\"]([^'\"]+)['\"]", params)
                            a = re.search(r"a[:\s]*['\"]?(\d+)", params)
                            
                            if h and e and f:
                                return {
                                    'h': h.group(1),
                                    'e': e.group(1),
                                    'f': f.group(1),
                                    'a': int(a.group(1)) if a else 3
                                }
    except Exception as e:
        logger.error(f"Erreur scraping: {e}")
    
    return None

# --- ROUTE ---

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if 'eleve.html' in school_url:
            base_url = school_url.split('eleve.html')[0]
        else:
            base_url = school_url if school_url.endswith('/') else school_url + '/'
            
        pronote_url = base_url + 'eleve.html'
        
        logger.info(f"=== SYNCHRO {username} ===")
        
        client = None
        
        # 1. SCRAPING + CLIENT CUSTOM
        logger.info(">>> Strategie 1: Scraping + Custom Client")
        auth = login_cas_scraping(username, password, pronote_url)
        
        if auth:
            try:
                logger.info(f"Auth reussie (h={auth['h']}), creation CustomClient...")
                client = CustomClient(pronote_url, auth)
                logger.info(f"✅ CONNECTE: {client.info.name}")
            except Exception as e:
                logger.warning(f"Echec CustomClient: {e}")
                import traceback
                traceback.print_exc()

        if not client:
            return jsonify({'error': 'Echec connexion. Verifiez identifiants ou reessayez.'}), 401

        # DATA
        result = {
            'studentData': {'name': client.info.name, 'class': client.info.class_name, 'average': 0},
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': []
        }

        # EDT
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            for day in range(5):
                for l in client.lessons(monday + timedelta(days=day)):
                    result['schedule'][day].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-indigo-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
        except: pass

        # Devoirs
        try:
            for i, hw in enumerate(client.homework(datetime.now(), datetime.now() + timedelta(days=14))):
                result['homework'].append({
                    'id': i,
                    'subject': hw.subject.name if hw.subject else 'Devoir',
                    'title': hw.description,
                    'dueDate': hw.date.strftime('%d/%m'),
                    'done': getattr(hw, 'done', False),
                    'color': 'bg-indigo-500'
                })
        except: pass

        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
