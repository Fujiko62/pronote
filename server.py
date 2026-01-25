from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def login_ent_77(username, password, pronote_url):
    """Authentification ENT Seine-et-Marne"""
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    
    logger.info("=== AUTH ENT 77 ===")
    
    try:
        # Etape 1: Aller sur Pronote
        resp1 = session.get(pronote_url, allow_redirects=True)
        
        soup = BeautifulSoup(resp1.text, 'html.parser')
        form = soup.find('form')
        if not form:
            return None
        
        action = form.get('action', '')
        parsed = urlparse(resp1.url)
        callback = parse_qs(parsed.query).get('callback', [''])[0]
        
        # Etape 2: Login
        login_url = f"{action}?callback={callback}" if callback else action
        
        resp2 = session.post(
            login_url,
            data={'email': username, 'password': password},
            allow_redirects=True,
            headers={'Referer': resp1.url, 'Origin': 'https://ent.seine-et-marne.fr'}
        )
        
        logger.info(f"URL finale: {resp2.url}")
        
        if 'pronote' in resp2.url.lower() and 'identifiant=' in resp2.url:
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
                        logger.info(f"✅ Auth OK: h={h.group(1)}")
                        return {
                            'url': resp2.url,
                            'html': resp2.text,
                            'h': h.group(1),
                            'e': e.group(1),
                            'f': f.group(1),
                            'session': session,
                            'cookies': dict(session.cookies)
                        }
        return None
    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

class CustomClient(pronotepy.Client):
    """Client Pronote personnalise qui accepte une session pre-authentifiee"""
    
    def __init__(self, pronote_url, auth_data):
        # On override completement l'init pour utiliser notre session
        self.auth_data = auth_data
        
        # Appeler le parent avec les credentials ENT
        super().__init__(
            pronote_url,
            username=auth_data['e'],
            password=auth_data['f']
        )

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
        
        # Authentification ENT
        auth = login_ent_77(username, password, pronote_url)
        
        if not auth:
            return jsonify({'error': 'Echec authentification ENT. Verifiez email/mot de passe.'}), 401
        
        logger.info("Auth ENT OK, creation client Pronote...")
        
        # Utiliser l'URL AVEC l'identifiant
        # C'est la cle: on utilise l'URL complete retournee par l'ENT
        try:
            # L'URL contient deja ?identifiant=xxx
            # On doit utiliser e et f comme credentials
            client = pronotepy.Client(
                auth['url'],  # URL avec ?identifiant=xxx
                username=auth['e'],
                password=auth['f']
            )
        except Exception as e:
            logger.warning(f"Tentative 1 echouee: {e}")
            
            # Essayer avec l'URL de base + credentials ENT
            try:
                # Extraire l'identifiant
                parsed = urlparse(auth['url'])
                identifiant = parse_qs(parsed.query).get('identifiant', [''])[0]
                base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                
                logger.info(f"Tentative 2: {base_url} avec identifiant={identifiant[:10]}...")
                
                # Creer une session avec les cookies ENT
                import pronotepy.pronoteAPI as pronoteAPI
                
                # Monkey-patch pour injecter nos cookies
                original_init = pronoteAPI.ClientBase.__init__
                
                def patched_init(self, pronote_url, *args, **kwargs):
                    # Injecter la session avec cookies
                    self._session = auth['session']
                    original_init(self, pronote_url, *args, **kwargs)
                
                # Ce n'est pas ideal mais ca peut marcher...
                # En fait, essayons autre chose
                
                # Le plus simple: utiliser directement les donnees qu'on a deja!
                # On a le HTML de la page Pronote, on peut l'utiliser
                
                raise Exception("Voir methode alternative")
                
            except Exception as e2:
                logger.warning(f"Tentative 2 echouee: {e2}")
        
        # Si pronotepy ne marche pas, on extrait les donnees nous-memes
        # depuis le HTML qu'on a deja!
        if not client or not client.logged_in:
            logger.info("Utilisation methode alternative...")
            
            # On a deja la page Pronote dans auth['html']
            # Mais pour les donnees, il faut faire des requetes API
            # C'est plus complexe...
            
            # Pour l'instant, retournons au moins les infos de base
            # qu'on peut extraire
            
            return jsonify({
                'error': 'Authentification ENT OK mais pronotepy incompatible. Utilisez la saisie manuelle.',
                'debug': {
                    'auth_success': True,
                    'pronote_url': auth['url'],
                    'session_id': auth['h']
                }
            }), 401
        
        logger.info(f"✅ CONNECTE: {client.info.name}")
        
        # Recuperer les donnees
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0
            },
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': [],
            'subjectAverages': [],
            'messages': []
        }

        # EDT
        try:
            monday = datetime.now() - timedelta(days=datetime.now().weekday())
            for day in range(5):
                for l in client.lessons(monday + timedelta(days=day)):
                    result['schedule'][day].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-red-500' if l.canceled else 'bg-indigo-500'
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
        except: pass

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
