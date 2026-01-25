from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
import logging
import re

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def login_ent_seine_et_marne(username, password, pronote_url):
    """
    Authentification personnalisee pour l'ENT Seine-et-Marne
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
    })
    
    logger.info("=== Authentification ENT Seine-et-Marne ===")
    
    try:
        # Etape 1: Acceder a Pronote
        logger.info("Etape 1: Acces Pronote...")
        resp1 = session.get(pronote_url, allow_redirects=True)
        logger.info(f"URL apres redirection: {resp1.url}")
        
        # Sauvegarder le callback pour plus tard
        parsed_url = urlparse(resp1.url)
        callback = parse_qs(parsed_url.query).get('callback', [''])[0]
        logger.info(f"Callback: {callback[:80]}...")
        
        # Etape 2: Parser le formulaire
        soup = BeautifulSoup(resp1.text, 'html.parser')
        
        # Chercher le formulaire
        form = soup.find('form')
        if not form:
            # Peut-etre que le formulaire est dans un iframe ou charge par JS
            logger.warning("Pas de formulaire trouve, recherche alternative...")
            
            # Chercher des liens de connexion
            login_link = soup.find('a', href=re.compile(r'auth|login|connect', re.I))
            if login_link:
                logger.info(f"Lien de connexion trouve: {login_link.get('href')}")
            
            return None
        
        # Recuperer l'action du formulaire
        action = form.get('action', '')
        method = form.get('method', 'POST').upper()
        
        logger.info(f"Formulaire: action={action}, method={method}")
        
        # Recuperer TOUS les champs (y compris hidden)
        form_data = {}
        for inp in form.find_all(['input', 'select', 'textarea']):
            name = inp.get('name')
            if not name:
                continue
            
            input_type = inp.get('type', 'text').lower()
            value = inp.get('value', '')
            
            # Pour les checkbox/radio, ne prendre que si checked
            if input_type in ['checkbox', 'radio']:
                if inp.get('checked'):
                    form_data[name] = value or 'on'
            else:
                form_data[name] = value
            
            logger.debug(f"  Champ [{input_type}]: {name} = '{value[:30] if value else ''}'")
        
        # Remplir les identifiants
        # Chercher le champ email/username
        email_fields = ['email', 'mail', 'username', 'login', 'identifiant', 'user']
        for field in email_fields:
            if field in form_data:
                form_data[field] = username
                logger.info(f"  → Username dans '{field}'")
                break
        
        # Chercher le champ password
        pwd_fields = ['password', 'passwd', 'pwd', 'pass', 'mdp', 'motdepasse']
        for field in pwd_fields:
            if field in form_data:
                form_data[field] = password
                logger.info(f"  → Password dans '{field}'")
                break
        
        # Ajouter le callback si present dans le formulaire
        if callback and 'callback' in form_data:
            form_data['callback'] = callback
        
        # Construire l'URL d'action complete
        if action.startswith('http'):
            action_url = action
        elif action.startswith('/'):
            action_url = f"{parsed_url.scheme}://{parsed_url.netloc}{action}"
        else:
            action_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{action}"
        
        # Ajouter le callback a l'URL si necessaire
        if callback and '?' not in action_url:
            action_url = f"{action_url}?callback={callback}"
        
        logger.info(f"Etape 3: POST vers {action_url}")
        logger.debug(f"Donnees: {list(form_data.keys())}")
        
        # Envoyer le formulaire
        resp2 = session.post(
            action_url, 
            data=form_data, 
            allow_redirects=True,
            headers={
                'Referer': resp1.url,
                'Origin': f"{parsed_url.scheme}://{parsed_url.netloc}"
            }
        )
        
        logger.info(f"Reponse: {resp2.status_code}, URL: {resp2.url}")
        
        # Verifier si on a reussi
        if 'pronote' in resp2.url.lower():
            logger.info("✅ Redirection vers Pronote!")
            
            # Verifier qu'on a bien la page Pronote
            if 'onload' in resp2.text and 'Start' in resp2.text:
                logger.info("✅ Page Pronote valide detectee!")
                return session, resp2
            else:
                logger.warning("Page Pronote mais pas de onload/Start")
        
        # Verifier s'il y a une erreur dans la reponse
        soup2 = BeautifulSoup(resp2.text, 'html.parser')
        error_div = soup2.find(class_=re.compile(r'error|erreur|alert|warning', re.I))
        if error_div:
            logger.warning(f"Erreur detectee: {error_div.get_text()[:100]}")
        
        # Chercher si on doit encore suivre des redirections
        meta_refresh = soup2.find('meta', attrs={'http-equiv': re.compile(r'refresh', re.I)})
        if meta_refresh:
            content = meta_refresh.get('content', '')
            logger.info(f"Meta refresh trouve: {content}")
        
        # Verifier les cookies de session
        logger.info(f"Cookies: {list(session.cookies.keys())}")
        
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
        
        logger.info(f"=== SYNCHRO pour {username} ===")
        
        client = None
        last_error = ""
        
        # Methode 1: Notre ENT personnalise
        try:
            logger.info(">>> Methode: ENT Seine-et-Marne (scraping)")
            result = login_ent_seine_et_marne(username, password, pronote_url)
            
            if result:
                session, resp = result
                # Essayer de creer le client avec la session
                # On doit extraire les parametres de la page Pronote
                logger.info("Tentative de creation du client Pronote...")
                
                # Parser la page pour extraire les infos de session
                soup = BeautifulSoup(resp.text, 'html.parser')
                body = soup.find('body')
                if body and body.get('onload'):
                    onload = body.get('onload')
                    logger.info(f"onload trouve: {onload[:100]}")
                    
                    # Le client pronotepy peut etre initialise avec les cookies
                    client = pronotepy.Client(pronote_url, cookies=session.cookies)
                    if client.logged_in:
                        logger.info("✅ Client Pronote cree!")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"❌ Scraping: {last_error[:100]}")
            client = None
        
        # Methode 2: ENT standards
        if not client or not client.logged_in:
            import pronotepy.ent as ent_module
            
            for ent_name in ['ent77', 'ile_de_france']:
                if not hasattr(ent_module, ent_name):
                    continue
                try:
                    logger.info(f">>> Methode: {ent_name}")
                    ent_func = getattr(ent_module, ent_name)
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                    if client.logged_in:
                        logger.info(f"✅ Connecte via {ent_name}")
                        break
                    client = None
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"❌ {ent_name}: {last_error[:80]}")
                    client = None

        if not client or not client.logged_in:
            return jsonify({'error': f'Echec. Verifiez vos identifiants. ({last_error[:50]})'}), 401

        # Recuperation des donnees
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
        except: pass

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
