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
    """Authentification ENT Seine-et-Marne avec gestion complete des cookies"""
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
    })
    
    logger.info("=== AUTH ENT 77 ===")
    
    try:
        # Etape 1: Aller sur Pronote pour etre redirige vers l'ENT
        logger.info(f"1. Acces {pronote_url}")
        resp1 = session.get(pronote_url, allow_redirects=True)
        logger.info(f"   → URL: {resp1.url}")
        logger.info(f"   → Cookies: {list(session.cookies.keys())}")
        
        # Parser la page pour trouver le formulaire
        soup = BeautifulSoup(resp1.text, 'html.parser')
        form = soup.find('form')
        
        if not form:
            logger.error("Pas de formulaire trouve!")
            return None
        
        action = form.get('action', '')
        logger.info(f"   → Form action: {action}")
        
        # Recuperer le callback de l'URL
        parsed = urlparse(resp1.url)
        callback = parse_qs(parsed.query).get('callback', [''])[0]
        logger.info(f"   → Callback: {callback[:60]}...")
        
        # Etape 2: Soumettre le formulaire de login
        # L'action pointe vers ent77, on doit garder le callback
        if callback:
            login_url = f"{action}?callback={callback}"
        else:
            login_url = action
        
        form_data = {
            'email': username,
            'password': password
        }
        
        logger.info(f"2. POST {login_url[:80]}...")
        
        # Important: envoyer le Referer correct
        resp2 = session.post(
            login_url,
            data=form_data,
            allow_redirects=True,
            headers={
                'Referer': resp1.url,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://ent.seine-et-marne.fr'
            }
        )
        
        logger.info(f"   → Status: {resp2.status_code}")
        logger.info(f"   → URL finale: {resp2.url}")
        logger.info(f"   → Cookies: {list(session.cookies.keys())}")
        
        # Verifier si on est sur Pronote
        if 'pronote' in resp2.url.lower() and 'eleve.html' in resp2.url.lower():
            logger.info("   ✅ Sur Pronote!")
            
            # Extraire les parametres du onload
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
            body = soup2.find('body')
            
            if body and body.get('onload'):
                onload = body.get('onload')
                logger.info(f"   → onload: {onload[:100]}...")
                
                # Extraire h, e, f
                match = re.search(r"Start\s*\(\s*\{([^}]+)\}", onload)
                if match:
                    params = match.group(1)
                    h = re.search(r"h[:\s]*['\"]?(\d+)", params)
                    e = re.search(r"e[:\s]*['\"]([^'\"]+)['\"]", params)
                    f = re.search(r"f[:\s]*['\"]([^'\"]+)['\"]", params)
                    
                    if h and e and f:
                        logger.info(f"   ✅ Params: h={h.group(1)}, e={e.group(1)[:15]}...")
                        return {
                            'url': resp2.url,
                            'h': h.group(1),
                            'e': e.group(1),
                            'f': f.group(1),
                            'session': session
                        }
        
        # Verifier s'il y a une erreur
        if 'ent.seine-et-marne.fr' in resp2.url:
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
            # Chercher message d'erreur
            error = soup2.find(class_=re.compile(r'error|alert|warning', re.I))
            if error:
                logger.warning(f"   ❌ Erreur ENT: {error.get_text()[:100]}")
            else:
                logger.warning("   ❌ Retour sur ENT sans erreur visible (mauvais identifiants?)")
        
        return None
        
    except Exception as e:
        logger.error(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
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
        
        # Essayer notre methode custom
        auth = login_ent_77(username, password, pronote_url)
        
        if not auth:
            return jsonify({'error': 'Echec authentification. Verifiez email/mot de passe.'}), 401
        
        # On a les credentials, creer le client
        logger.info("Creation client Pronote...")
        
        try:
            # Methode: utiliser e et f comme credentials ENT
            client = pronotepy.Client(
                pronote_url,
                username=auth['e'],
                password=auth['f']
            )
            
            if not client.logged_in:
                raise Exception("Client non connecte")
                
        except Exception as e1:
            logger.warning(f"Methode 1 echouee: {e1}")
            
            # Methode 2: essayer avec ent77
            try:
                import pronotepy.ent as ent_module
                client = pronotepy.Client(
                    pronote_url,
                    username=username,
                    password=password,
                    ent=ent_module.ent77
                )
            except Exception as e2:
                logger.error(f"Methode 2 echouee: {e2}")
                return jsonify({'error': 'Connexion Pronote echouee'}), 401
        
        if not client.logged_in:
            return jsonify({'error': 'Non connecte a Pronote'}), 401
        
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
                    'urgent': (hw.date - datetime.now().date()).days < 2,
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
            logger.info(f"Notes: {count}, Moy: {result['studentData']['average']}")
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
