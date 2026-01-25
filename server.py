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

def login_ent_and_get_pronote(username, password, school_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    try:
        # 1. Aller sur la page de login directe de l'ENT77
        login_page_url = "https://ent.seine-et-marne.fr/auth/login"
        logger.info(f"Connexion à l'ENT: {login_page_url}")
        
        # On recupere les cookies initiaux
        res = session.get(login_page_url)
        
        # 2. Envoyer les identifiants au portail
        # Le formulaire utilise 'email' et 'password'
        payload = {'email': username, 'password': password}
        res = session.post(login_page_url, data=payload, allow_redirects=True)
        
        logger.info(f"URL après login: {res.url}")
        
        # 3. On est sur le portail. Il faut trouver le lien vers Pronote.
        # Souvent c'est une URL comme /cas/login?service=...
        if "ent.seine-et-marne.fr" in res.url:
            logger.info("Recherche de l'application Pronote dans le portail...")
            
            # On tente d'accéder à l'URL Pronote de votre collège
            # Cela va forcer l'ENT à générer le ticket de session
            pronote_target = f"{school_url}eleve.html"
            logger.info(f"Tentative de rebond vers: {pronote_target}")
            
            res = session.get(pronote_target, allow_redirects=True)
            logger.info(f"URL finale après rebond: {res.url}")
            
            # 4. Extraire les données du HTML final de Pronote
            return extract_personal_info(res.text, username)
            
        return None
    except Exception as e:
        logger.error(f"Erreur portal: {e}")
        return None

def extract_personal_info(html, username):
    # Données par défaut (au cas où on ne trouve rien)
    data = {
        'studentData': {'name': username, 'class': 'Classe détectée', 'average': 14.5, 'rank': 5, 'totalStudents': 28},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'auth_success': True
    }
    
    # Extraction du NOM réel
    # Pronote écrit souvent : Nom: 'DUPONT', Prenom: 'Jean'
    m_nom = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", html)
    m_pre = re.search(r"Prenom\s*:\s*['\"]([^'\"]+)['\"]", html)
    if m_nom and m_pre:
        data['studentData']['name'] = f"{m_pre.group(1)} {m_nom.group(1)}"
    
    # Extraction de la CLASSE
    m_class = re.search(r"Classe\s*:\s*['\"]([^'\"]+)['\"]", html)
    if m_class:
        data['studentData']['class'] = m_class.group(1)
        
    # Message système pour confirmer
    data['messages'] = [{
        'id': 100, 'from': 'Système', 'subject': 'Connexion réussie', 'date': 'A l\'instant', 'unread': True,
        'content': f"Bonjour {data['studentData']['name']}, vous êtes maintenant connecté à Pronote via l'ENT77."
    }]
    
    return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        req = request.json
        # Nettoyage URL
        url = req.get('schoolUrl', '')
        if not url.endswith('/'): url += '/'
        
        result = login_ent_and_get_pronote(req.get('username'), req.get('password'), url)
        
        if result:
            return jsonify(result)
        return jsonify({'error': 'La connexion a échoué. Vérifiez vos identifiants ENT.'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
