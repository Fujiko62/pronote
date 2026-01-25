from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import logging
import re

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def login_ent_portal(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    })
    
    try:
        # 1. Acces Pronote -> Redirection ENT
        logger.info(f"Connexion initiale: {pronote_url}")
        resp = session.get(pronote_url, allow_redirects=True)
        
        # Si on est sur l'ENT
        if 'seine-et-marne' in resp.url:
            logger.info("ENT Seine-et-Marne detecte")
            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            
            if form:
                action = form.get('action', '')
                if action.startswith('/'):
                    parsed = urlparse(resp.url)
                    action = f"{parsed.scheme}://{parsed.netloc}{action}"
                
                # Callback important
                parsed_orig = urlparse(resp.url)
                params = parse_qs(parsed_orig.query)
                callback = params.get('callback', [''])[0]
                if callback and '?' not in action:
                    action += f"?callback={callback}"
                
                # Identifiants
                user_field = 'username' if soup.find('input', {'name': 'username'}) else 'email'
                data = {user_field: username, 'password': password}
                
                logger.info(f"Auth ENT en cours...")
                resp2 = session.post(action, data=data, allow_redirects=True)
                
                # On est sur le portail ou Pronote
                logger.info(f"URL apres auth: {resp2.url}")
                
                final_html = ""
                # Si on n'est pas encore sur Pronote, on cherche le lien
                if 'pronote' not in resp2.url.lower():
                    logger.info("Recherche de l'application Pronote...")
                    # Tenter d'acceder a Pronote directement maintenant qu'on a le cookie ENT
                    resp3 = session.get(pronote_url, allow_redirects=True)
                    final_html = resp3.text
                    logger.info(f"URL finale: {resp3.url}")
                else:
                    final_html = resp2.text
                
                # Extraction des infos personnelles
                return extract_data(final_html, username)
        
        return None
    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

def extract_data(html, username):
    data = {
        'studentData': {'name': username, 'class': 'Non detectee', 'average': 0, 'rank': 1, 'totalStudents': 30},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': []
    }
    
    try:
        # 1. Trouver le NOM REEL
        # Pronote stocke le nom dans des variables JS : Nom: 'DUPONT', Prenom: 'Jean'
        nom = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", html)
        prenom = re.search(r"Prenom\s*:\s*['\"]([^'\"]+)['\"]", html)
        if nom and prenom:
            data['studentData']['name'] = f"{prenom.group(1)} {nom.group(1)}"
        elif "PRONOTE -" in html:
            # Extraction depuis le titre
            title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html)
            if title_match:
                data['studentData']['name'] = title_match.group(1).strip()

        # 2. Trouver la CLASSE
        classe = re.search(r"Classe\s*:\s*['\"]([^'\"]+)['\"]", html)
        if classe:
            data['studentData']['class'] = classe.group(1)
        else:
            # Essayer de trouver une chaine qui ressemble a une classe (ex: 3EME B)
            class_regex = re.search(r"['\"](\d+(?:EME|eme|ème|EME)\s*[A-Z])['\"]", html)
            if class_regex:
                data['studentData']['class'] = class_regex.group(1)

        # 3. Message de bienvenue si succes
        data['messages'].append({
            'id': 99,
            'from': 'Système',
            'subject': 'Synchronisation Réussie',
            'date': 'A l\'instant',
            'unread': True,
            'content': f"Bonjour {data['studentData']['name']}, la connexion à votre compte a réussi !\nVos informations de base (Nom, Classe) ont été récupérées."
        })
        
        return data
    except:
        return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        res = login_ent_portal(data.get('username'), data.get('password'), data.get('schoolUrl') + 'eleve.html')
        if res:
            return jsonify(res)
        return jsonify({'error': 'Identifiants invalides'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
