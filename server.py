from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
import re

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def login_ent_seine_et_marne(username, password, pronote_url):
    """
    Authentification personnalisee pour l'ENT Seine-et-Marne
    Gere le flux complexe de redirection
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    logger.info("=== Debut authentification ENT Seine-et-Marne ===")
    
    try:
        # Etape 1: Acceder a Pronote pour obtenir l'URL de redirection ENT
        logger.info("Etape 1: Acces initial a Pronote...")
        resp = session.get(pronote_url, allow_redirects=True)
        logger.debug(f"URL finale: {resp.url}")
        logger.debug(f"Status: {resp.status_code}")
        
        # Etape 2: Analyser la page de l'ENT
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Chercher le formulaire de connexion
        form = soup.find('form')
        if form:
            logger.info("Formulaire trouve!")
            action = form.get('action', '')
            logger.debug(f"Action du formulaire: {action}")
            
            # Extraire tous les champs du formulaire
            inputs = {}
            for inp in form.find_all('input'):
                name = inp.get('name')
                value = inp.get('value', '')
                if name:
                    inputs[name] = value
                    logger.debug(f"Champ: {name} = {value[:20] if value else '(vide)'}...")
            
            # Ajouter les identifiants
            # Chercher les noms de champs pour username/password
            for key in inputs.keys():
                if 'user' in key.lower() or 'login' in key.lower() or 'email' in key.lower():
                    inputs[key] = username
                    logger.info(f"Username dans le champ: {key}")
                elif 'pass' in key.lower() or 'pwd' in key.lower():
                    inputs[key] = password
                    logger.info(f"Password dans le champ: {key}")
            
            # Si pas trouve, essayer les noms standards
            if 'username' not in str(inputs.values()):
                inputs['username'] = username
            if 'password' not in str(inputs.values()):
                inputs['password'] = password
            
            # Construire l'URL d'action
            if action.startswith('/'):
                # URL relative
                from urllib.parse import urlparse
                parsed = urlparse(resp.url)
                action_url = f"{parsed.scheme}://{parsed.netloc}{action}"
            elif action.startswith('http'):
                action_url = action
            else:
                action_url = resp.url
            
            logger.info(f"Etape 2: Envoi du formulaire a {action_url}")
            
            # Envoyer le formulaire
            resp2 = session.post(action_url, data=inputs, allow_redirects=True)
            logger.debug(f"Reponse: {resp2.status_code}, URL: {resp2.url}")
            
            # Verifier si on est arrive sur Pronote
            if 'pronote' in resp2.url.lower() and 'eleve.html' in resp2.url.lower():
                logger.info("✅ Redirection vers Pronote reussie!")
                return session.cookies
        
        # Methode alternative: chercher des liens de connexion
        logger.info("Recherche de methodes alternatives...")
        
        # Chercher un bouton/lien de connexion
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            text = link.get_text().lower()
            if 'connect' in text or 'login' in text or 'auth' in href:
                logger.debug(f"Lien trouve: {text} -> {href}")
        
        # Chercher des scripts qui contiennent des URLs d'auth
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and ('login' in script.string.lower() or 'auth' in script.string.lower()):
                logger.debug(f"Script interessant trouve")
        
        logger.warning("Impossible de trouver le formulaire de connexion standard")
        return None
        
    except Exception as e:
        logger.error(f"Erreur lors de l'authentification: {e}")
        import traceback
        traceback.print_exc()
        return None

def custom_ent_77(username, password, pronote_url):
    """
    Fonction ENT personnalisee pour Seine-et-Marne
    Compatible avec pronotepy
    """
    cookies = login_ent_seine_et_marne(username, password, pronote_url)
    if cookies:
        return cookies
    raise Exception("Echec de l'authentification ENT Seine-et-Marne")

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
        
        logger.info(f"=== SYNCHRO pour {username} ===")
        
        client = None
        last_error = ""
        
        # Methode 1: Essayer notre ENT personnalise
        try:
            logger.info(">>> Essai : ENT Seine-et-Marne (custom)")
            cookies = login_ent_seine_et_marne(username, password, pronote_url)
            if cookies:
                # Creer une session avec les cookies
                client = pronotepy.Client(pronote_url, cookies=cookies)
                if client.logged_in:
                    logger.info("✅ CONNECTE via ENT custom!")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"❌ ENT custom: {last_error[:100]}")
            client = None
        
        # Methode 2: Essayer les ENT standards
        if not client or not client.logged_in:
            import pronotepy.ent as ent_module
            ent_list = []
            if hasattr(ent_module, 'ent77'):
                ent_list.append(('ent77', ent_module.ent77))
            if hasattr(ent_module, 'ile_de_france'):
                ent_list.append(('ile_de_france', ent_module.ile_de_france))
            ent_list.append(('Direct', None))
            
            for ent_name, ent_func in ent_list:
                try:
                    logger.info(f">>> Essai : {ent_name}")
                    if ent_func:
                        client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                    else:
                        client = pronotepy.Client(pronote_url, username=username, password=password)
                    
                    if client.logged_in:
                        logger.info(f"✅ CONNECTE via {ent_name}!")
                        break
                    client = None
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"❌ {ent_name}: {last_error[:80]}")
                    client = None

        if not client or not client.logged_in:
            return jsonify({'error': f'Echec connexion. {last_error[:80]}'}), 401

        # --- DONNEES ---
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

        # Emploi du temps
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
                        'color': 'bg-red-500' if l.canceled else 'bg-indigo-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
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
                        'comment': g.comment or '',
                        'average': round((val/mx)*20, 1)
                    })
                except: pass
            if count > 0:
                result['studentData']['average'] = round(total/count, 1)
        except Exception as e:
            logger.error(f"Notes: {e}")

        logger.info(f"=== FIN {client.info.name} ===")
        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/debug-ent', methods=['POST'])
def debug_ent():
    """Endpoint pour debugger la page de l'ENT"""
    try:
        data = request.json
        url = data.get('url', 'https://0771068t.index-education.net/pronote/eleve.html')
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        resp = session.get(url, allow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Extraire les infos utiles
        forms = soup.find_all('form')
        links = soup.find_all('a', href=True)[:20]
        
        return jsonify({
            'final_url': resp.url,
            'status': resp.status_code,
            'title': soup.title.string if soup.title else None,
            'forms_count': len(forms),
            'forms': [{'action': f.get('action'), 'method': f.get('method')} for f in forms],
            'links': [{'href': l.get('href'), 'text': l.get_text()[:50]} for l in links],
            'html_preview': resp.text[:2000]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
