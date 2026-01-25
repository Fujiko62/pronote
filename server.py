from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re
import functools

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UTILITAIRES ENT ---

def get_ent_function(name):
    """Recupere une fonction ENT sans planter"""
    try:
        import pronotepy.ent as ent_module
        if hasattr(ent_module, name):
            return getattr(ent_module, name)
    except: pass
    return None

# --- METHODE 1: SCRAPING CAS (Pour ENT 77 Web) ---

def login_cas_scraping(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    })
    
    try:
        # 1. Acces Pronote
        resp = session.get(pronote_url, allow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        if not form: return None
        
        # 2. Login
        action = form.get('action', '')
        parsed = urlparse(resp.url)
        callback = parse_qs(parsed.query).get('callback', [''])[0]
        login_url = f"{action}?callback={callback}" if callback else action
        
        resp = session.post(
            login_url,
            data={'email': username, 'password': password},
            headers={'Referer': resp.url, 'Origin': 'https://ent.seine-et-marne.fr'}
        )
        
        # 3. Extraction Session
        if 'identifiant=' in resp.url:
            soup = BeautifulSoup(resp.text, 'html.parser')
            body = soup.find('body')
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
                            'url': resp.url,
                            'h': h.group(1),
                            'e': e.group(1),
                            'f': f.group(1)
                        }
    except Exception as e:
        logger.error(f"Scraping error: {e}")
    return None

# --- ROUTE SYNC ---

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
            
        # Detecter si c'est une URL mobile
        is_mobile = 'mobile' in school_url
        
        if 'eleve.html' in school_url:
            base_url = school_url.split('eleve.html')[0]
        else:
            base_url = school_url if school_url.endswith('/') else school_url + '/'
            
        pronote_url = base_url + ('mobile.eleve.html' if is_mobile else 'eleve.html')
        
        logger.info(f"=== SYNCHRO {username} ({'Mobile' if is_mobile else 'Web'}) ===")
        
        client = None
        
        # --- STRATEGIE 1: SCRAPING (Web seulement) ---
        if not is_mobile:
            logger.info(">>> Strategie 1: Scraping CAS")
            auth = login_cas_scraping(username, password, pronote_url)
            if auth:
                try:
                    client = pronotepy.Client(auth['url'], username=auth['e'], password=auth['f'])
                    if client.logged_in:
                        logger.info("✅ CONNECTE via Scraping")
                except Exception as e:
                    logger.warning(f"Echec client scraping: {e}")

        # --- STRATEGIE 2: ENT PRONOTEPY ---
        if not client:
            logger.info(">>> Strategie 2: ENT Pronotepy")
            ent_to_try = ['ent77', 'ent_77', 'ile_de_france']
            
            for ent_name in ent_to_try:
                ent_func = get_ent_function(ent_name)
                if not ent_func: continue
                
                try:
                    logger.info(f"Essai {ent_name}...")
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                    if client.logged_in:
                        logger.info(f"✅ CONNECTE via {ent_name}")
                        break
                    client = None
                except Exception as e:
                    logger.warning(f"Echec {ent_name}: {e}")

        # --- STRATEGIE 3: DIRECT ---
        if not client:
            logger.info(">>> Strategie 3: Direct")
            try:
                client = pronotepy.Client(pronote_url, username=username, password=password)
                if client.logged_in:
                    logger.info("✅ CONNECTE Direct")
            except: pass

        if not client or not client.logged_in:
            return jsonify({'error': 'Echec connexion. Verifiez vos identifiants.'}), 401

        # --- RECUPERATION DONNEES ---
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0
            },
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

        # Notes (Web seulement)
        if not is_mobile:
            try:
                period = client.current_period
                total, count = 0, 0
                for g in period.grades[:20]:
                    val = float(g.grade.replace(',', '.'))
                    mx = float(g.out_of.replace(',', '.'))
                    total += (val/mx)*20
                    count += 1
                    result['grades'].append({
                        'subject': g.subject.name,
                        'grade': val,
                        'max': mx,
                        'date': g.date.strftime('%d/%m'),
                        'average': round((val/mx)*20, 1)
                    })
                if count > 0:
                    result['studentData']['average'] = round(total/count, 1)
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
