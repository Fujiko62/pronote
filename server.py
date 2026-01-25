from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
import logging
import re
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_pronote_clone(username, password, pronote_url):
    session = requests.Session()
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 AVG/143.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    })
    
    try:
        logger.info(f"1. GET {pronote_url}")
        res = session.get(pronote_url, allow_redirects=True)
        
        soup = BeautifulSoup(res.text, 'html.parser')
        form = soup.find('form')
        
        if form:
            action = form.get('action')
            if action.startswith('/'):
                parsed = urlparse(res.url)
                action = f"{parsed.scheme}://{parsed.netloc}{action}"
            
            parsed_url = urlparse(res.url)
            callback = parse_qs(parsed_url.query).get('callback', [''])[0]
            if callback and '?' not in action:
                action += f"?callback={callback}"
            
            user_field = 'email'
            if soup.find('input', {'name': 'username'}): user_field = 'username'
            
            post_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://ent.seine-et-marne.fr',
                'Referer': res.url
            }
            
            logger.info(f"2. POST Identifiants...")
            res_login = session.post(
                action, 
                data={user_field: username, 'password': password},
                headers=post_headers,
                allow_redirects=True
            )
            
            final_res = res_login
            if "ent.seine-et-marne" in res_login.url and callback:
                final_res = session.get(callback, allow_redirects=True)
                
            if "pronote" in final_res.url.lower():
                logger.info("✅ SUCCES : Page Pronote atteinte !")
                
                # On essaie d'extraire le nom depuis le HTML
                data = extract_data(final_res.text, username)
                
                # Si le nom n'est pas trouvé, on utilise l'identifiant ENT formaté
                if data['studentData']['name'] == username:
                    # Formater "prenom.nom" en "Prenom Nom"
                    formatted_name = username.split('@')[0].replace('.', ' ').title()
                    data['studentData']['name'] = formatted_name
                    
                return data
                
        return None

    except Exception as e:
        logger.error(f"Erreur : {e}")
        return None

def extract_data(html, username):
    data = {
        'studentData': {'name': username, 'class': 'Classe inconnue', 'average': 0, 'rank': 1, 'totalStudents': 30},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'subjectAverages': [],
        'auth_success': True
    }
    
    try:
        # Essayer de trouver le nom dans le titre ou les balises meta
        title_match = re.search(r"<title>PRONOTE\s*-\s*([^-\n<]+)", html, re.I)
        if title_match:
            full_name = title_match.group(1).strip()
            full_name = full_name.replace("ESPACE ÉLÈVE", "").strip()
            if full_name:
                data['studentData']['name'] = full_name

        # Chercher dans les scripts JS (variables globales)
        script_match = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", html)
        if script_match:
            data['studentData']['name'] = script_match.group(1)

        # Message de succès
        data['messages'].append({
            'id': 1,
            'from': 'Système',
            'subject': 'Connexion Réussie',
            'date': 'Maintenant',
            'unread': True,
            'content': f"Authentification réussie pour {data['studentData']['name']} ! Les données détaillées sont chiffrées par Pronote."
        })

        return data
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
        return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        req = request.json
        url = req.get('schoolUrl', '')
        if not url.endswith('/'): url += '/'
        
        result = sync_pronote_clone(req.get('username'), req.get('password'), url + 'eleve.html')
        
        if result:
            return jsonify(result)
        return jsonify({'error': 'Échec de connexion'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
