from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import logging
import re
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def login_ent_portal(username, password, pronote_url):
    """
    Connexion via le portail ENT (Authentification + Clic sur l'app Pronote)
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    logger.info("=== Connexion Portail ENT ===")
    
    try:
        # Etape 1: Tenter d'acceder a Pronote directement (pour declencher l'auth CAS)
        logger.info(f"Acces initial: {pronote_url}")
        resp = session.get(pronote_url, allow_redirects=True)
        
        # Si on est redirige vers l'ENT
        if 'ent' in resp.url and 'auth' in resp.url:
            logger.info("Redirection ENT detectee")
            
            # Recuperer le formulaire
            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            
            if form:
                action = form.get('action', '')
                if action.startswith('/'):
                    parsed = urlparse(resp.url)
                    action = f"{parsed.scheme}://{parsed.netloc}{action}"
                
                # Garder le callback s'il existe
                parsed_orig = urlparse(resp.url)
                callback = parse_qs(parsed_orig.query).get('callback', [''])[0]
                if callback and '?' not in action:
                    action += f"?callback={callback}"
                
                # POST Identifiants
                user_field = 'username' if soup.find('input', {'name': 'username'}) else 'email'
                pass_field = 'password'
                
                logger.info(f"Envoi identifiants vers {action}")
                resp2 = session.post(
                    action, 
                    data={user_field: username, pass_field: password},
                    allow_redirects=True,
                    headers={'Referer': resp.url}
                )
                
                # Etape 2: On est connecte a l'ENT, maintenant chercher Pronote
                logger.info(f"Page apres login: {resp2.url}")
                
                # Si on n'est pas redirige vers Pronote directement
                if 'pronote' not in resp2.url.lower():
                    logger.info("Recherche du lien Pronote dans le portail...")
                    soup2 = BeautifulSoup(resp2.text, 'html.parser')
                    
                    # Chercher tous les liens
                    links = soup2.find_all('a', href=True)
                    pronote_link = None
                    
                    for link in links:
                        href = link['href']
                        text = link.get_text().lower()
                        # Criteres de recherche
                        if 'pronote' in href.lower() or 'pronote' in text:
                            pronote_link = href
                            break
                    
                    if pronote_link:
                        logger.info(f"Lien Pronote trouve: {pronote_link}")
                        if pronote_link.startswith('/'):
                            parsed = urlparse(resp2.url)
                            pronote_link = f"{parsed.scheme}://{parsed.netloc}{pronote_link}"
                            
                        # Clic sur le lien Pronote
                        resp3 = session.get(pronote_link, allow_redirects=True)
                        if 'pronote' in resp3.url.lower():
                            return extract_pronote_data(resp3.text, username)
                    else:
                        logger.warning("Lien Pronote introuvable dans le portail")
                        # Essayons d'acceder a l'URL Pronote directement maintenant qu'on est connecte
                        resp3 = session.get(pronote_url, allow_redirects=True)
                        if 'pronote' in resp3.url.lower():
                            return extract_pronote_data(resp3.text, username)
                
                elif 'pronote' in resp2.url.lower():
                    return extract_pronote_data(resp2.text, username)

    except Exception as e:
        logger.error(f"Erreur: {e}")
    
    return None

def extract_pronote_data(html, username):
    """Extrait le nom et la classe depuis le HTML de Pronote"""
    data = {
        'studentData': {'name': username, 'class': 'Non detectee', 'average': 0},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'auth_success': True
    }
    
    try:
        # Essayer de trouver le nom dans le titre ou les scripts
        if "PRONOTE" in html:
            # Chercher dans les variables JS
            name_match = re.search(r"Nom['\"]?:\s*['\"]([^'\"]+)['\"]", html)
            if name_match:
                data['studentData']['name'] = name_match.group(1)
                
            class_match = re.search(r"Classe['\"]?:\s*['\"]([^'\"]+)['\"]", html)
            if class_match:
                data['studentData']['class'] = class_match.group(1)
                
        logger.info(f"Donnees extraites: {data['studentData']['name']}")
        return data
    except:
        return data

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
        
        logger.info(f"=== SYNCHRO PORTAIL {username} ===")
        
        result = login_ent_portal(username, password, pronote_url)
        
        if result:
            return jsonify(result)
        else:
            return jsonify({'error': 'Echec connexion. Verifiez vos identifiants.'}), 401

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
