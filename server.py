from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re
import socket

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UTILITAIRES ---

def get_ent_function(name):
    try:
        import pronotepy.ent as ent_module
        if hasattr(ent_module, name):
            return getattr(ent_module, name)
    except: pass
    return None

def check_dns(hostname):
    try:
        socket.gethostbyname(hostname)
        return True
    except:
        return False

# --- SCRAPING CAS ---

def login_cas_scraping(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    logger.info("--- Debut Scraping ---")
    
    try:
        # 1. Acces Pronote
        logger.info(f"GET {pronote_url}")
        resp = session.get(pronote_url, allow_redirects=True, timeout=10)
        logger.info(f"URL finale: {resp.url}")
        
        # Si on est redirige vers l'ENT
        if 'ent' in resp.url:
            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            
            if form:
                action = form.get('action', '')
                logger.info(f"Formulaire trouve: {action}")
                
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
                
                # Si input name="username" existe
                if soup.find('input', {'name': 'username'}): user_field = 'username'
                if soup.find('input', {'name': 'login'}): user_field = 'login'
                if soup.find('input', {'name': 'user'}): user_field = 'user'
                
                logger.info(f"Champs identifies: {user_field} / {pass_field}")
                
                # POST
                data = {user_field: username, pass_field: password}
                logger.info(f"POST {action}")
                
                resp2 = session.post(
                    action,
                    data=data,
                    allow_redirects=True,
                    headers={'Referer': resp.url}
                )
                
                logger.info(f"Reponse POST: {resp2.status_code} - {resp2.url}")
                
                # Verification Pronote
                if 'pronote' in resp2.url.lower():
                    # Chercher les params de session
                    if 'identifiant=' in resp2.url:
                        logger.info("✅ URL avec identifiant detectee!")
                        # On a reussi!
                        # On peut extraire h, e, f du HTML
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
                                if h and e and f:
                                    return {
                                        'url': resp2.url,
                                        'h': h.group(1),
                                        'e': e.group(1),
                                        'f': f.group(1)
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
        
        # 1. SCRAPING
        logger.info(">>> Strategie 1: Scraping")
        auth = login_cas_scraping(username, password, pronote_url)
        
        if auth:
            try:
                logger.info("Auth reussie, creation client...")
                client = pronotepy.Client(auth['url'], username=auth['e'], password=auth['f'])
            except Exception as e:
                logger.warning(f"Echec client scraping: {e}")
        
        # 2. ENT STANDARD
        if not client:
            logger.info(">>> Strategie 2: ENT Standard")
            
            # Verifier DNS avant
            if not check_dns('ent77.seine-et-marne.fr'):
                logger.warning("⚠️ Impossible de resoudre ent77.seine-et-marne.fr")
            
            ent_list = ['ent77', 'ent_77', 'ile_de_france']
            for name in ent_list:
                func = get_ent_function(name)
                if func:
                    try:
                        logger.info(f"Essai {name}...")
                        client = pronotepy.Client(pronote_url, username=username, password=password, ent=func)
                        if client.logged_in:
                            logger.info("✅ CONNECTE")
                            break
                        client = None
                    except Exception as e:
                        logger.warning(f"Echec {name}: {e}")

        # 3. DIRECT
        if not client:
            logger.info(">>> Strategie 3: Direct")
            try:
                client = pronotepy.Client(pronote_url, username=username, password=password)
            except: pass

        if not client or not client.logged_in:
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
