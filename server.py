from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def login_ent_77(username, password, pronote_url):
    """Authentification ENT Seine-et-Marne renforcee"""
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1'
    })
    
    logger.info("=== AUTH ENT 77 RENFORCEE ===")
    
    try:
        # Etape 1: Acces Pronote
        resp1 = session.get(pronote_url, allow_redirects=True)
        logger.info(f"1. Acces initial: {resp1.url}")
        
        soup = BeautifulSoup(resp1.text, 'html.parser')
        form = soup.find('form')
        if not form:
            logger.error("Pas de formulaire!")
            return None
        
        action = form.get('action', '')
        parsed = urlparse(resp1.url)
        callback = parse_qs(parsed.query).get('callback', [''])[0]
        
        # Etape 2: Login
        login_url = f"{action}?callback={callback}" if callback else action
        
        # Headers specifiques pour le POST
        post_headers = {
            'Origin': 'https://ent.seine-et-marne.fr',
            'Referer': resp1.url,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        logger.info(f"2. POST {login_url[:60]}...")
        
        resp2 = session.post(
            login_url,
            data={'email': username, 'password': password},
            allow_redirects=True,
            headers=post_headers
        )
        
        logger.info(f"   Status: {resp2.status_code}")
        logger.info(f"   URL: {resp2.url}")
        
        # Si on est redirige vers Pronote avec identifiant
        if 'pronote' in resp2.url.lower() and 'identifiant=' in resp2.url:
            logger.info("   ✅ Redirection Pronote OK")
            
            # Verifier le contenu de la page
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
            body = soup2.find('body')
            
            if body:
                onload = body.get('onload', '')
                if 'Start' in onload:
                    match = re.search(r"Start\s*\(\s*\{([^}]+)\}", onload)
                    if match:
                        logger.info("   ✅ Parametres Start trouves!")
                        params = match.group(1)
                        h = re.search(r"h[:\s]*['\"]?(\d+)", params)
                        e = re.search(r"e[:\s]*['\"]([^'\"]+)['\"]", params)
                        f = re.search(r"f[:\s]*['\"]([^'\"]+)['\"]", params)
                        
                        if h and e and f:
                            return {
                                'url': resp2.url,
                                'h': h.group(1),
                                'e': e.group(1),
                                'f': f.group(1),
                                'session': session
                            }
                else:
                    logger.warning(f"   ⚠️ Page Pronote invalide (taille: {len(resp2.text)})")
                    logger.warning(f"   Body: {body.get_text()[:200]}")
                    
                    # Peut-etre une redirection JS ?
                    script = soup2.find('script')
                    if script and 'location.replace' in str(script):
                        logger.info("   🔄 Redirection JS detectee")
                        # TODO: Gerer redirection JS si besoin
        
        return None
    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        logger.info(f"=== SYNCHRO {username} ===")
        
        auth = login_ent_77(username, password, pronote_url)
        
        if not auth:
            return jsonify({'error': 'Echec auth ENT. Verifiez identifiants.'}), 401
        
        logger.info("Auth ENT OK, creation client Pronote...")
        
        # Creer client avec les credentials ENT
        try:
            client = pronotepy.Client(
                auth['url'],
                username=auth['e'],
                password=auth['f']
            )
        except Exception as e:
            logger.error(f"Erreur client: {e}")
            return jsonify({'error': 'Erreur connexion Pronote'}), 401
        
        if not client.logged_in:
            return jsonify({'error': 'Non connecte a Pronote'}), 401
        
        logger.info(f"✅ CONNECTE: {client.info.name}")
        
        # Recuperer les donnees
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0,
                'rank': 1,
                'totalStudents': 30
            },
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': [],
            'subjectAverages': [],
            'messages': []
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
            logger.info(f"EDT: {sum(len(d) for d in result['schedule'])} cours")
        except Exception as e:
            logger.error(f"EDT: {e}")

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
            logger.info(f"Devoirs: {len(result['homework'])}")
        except Exception as e:
            logger.error(f"Devoirs: {e}")

        # Notes
        try:
            period = client.current_period
            total, count = 0, 0
            for g in period.grades[:20]:
                try:
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
                except: pass
            if count > 0:
                result['studentData']['average'] = round(total/count, 1)
            logger.info(f"Notes: {len(result['grades'])}")
        except Exception as e:
            logger.error(f"Notes: {e}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
