from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
import logging
import re
import datetime

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_via_proxy(username, password, school_url):
    session = requests.Session()
    
    # Headers tres complets pour imiter un navigateur
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1'
    })
    
    try:
        # 1. On va sur l'ENT directement
        logger.info("1. Acces direct ENT...")
        ent_url = "https://ent.seine-et-marne.fr/auth/login"
        
        # On recupere la page pour avoir le CSRF token s'il y en a un
        res = session.get(ent_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # On prepare le login
        # Il faut inclure le callback vers Pronote DANS le login
        pronote_callback = f"{school_url}eleve.html"
        login_url_with_callback = f"{ent_url}?callback={requests.utils.quote(pronote_callback)}"
        
        logger.info(f"2. Login sur {login_url_with_callback}")
        
        # On cherche le nom des champs input
        user_field = 'email'
        if soup.find('input', {'name': 'username'}): user_field = 'username'
        
        payload = {
            user_field: username,
            'password': password
        }
        
        # 2. POST Login
        res_login = session.post(
            login_url_with_callback,
            data=payload,
            allow_redirects=True,
            headers={
                'Origin': 'https://ent.seine-et-marne.fr',
                'Referer': ent_url
            }
        )
        
        logger.info(f"   URL apres login: {res_login.url}")
        
        # 3. Si on n'est pas sur Pronote, on force l'acces
        if "pronote" not in res_login.url.lower():
            logger.info("3. Forçage acces Pronote...")
            res_final = session.get(pronote_callback, allow_redirects=True)
        else:
            res_final = res_login
            
        logger.info(f"   URL finale: {res_final.url}")
        
        # 4. Extraction
        if "pronote" in res_final.url.lower():
            return extract_data_perfect(res_final.text, username)
            
        return None

    except Exception as e:
        logger.error(f"Erreur proxy: {e}")
        return None

def extract_data_perfect(html, username):
    data = {
        'studentData': {'name': username.replace('.', ' ').title(), 'class': 'Non détectée', 'average': 0},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'auth_success': True
    }
    
    try:
        # Nom
        title_match = re.search(r"<title>PRONOTE\s*-\s*([^-\n<]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # Emploi du temps
        soup = BeautifulSoup(html, 'html.parser')
        spans = soup.find_all('span', class_='sr-only')
        
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0
        
        count = 0
        for span in spans:
            text = span.get_text()
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': m.group(3).strip(),
                    'teacher': 'Professeur',
                    'room': 'Salle',
                    'color': 'bg-indigo-500'
                })
                count += 1
        
        logger.info(f"✅ {count} cours trouves")
        return data
    except Exception as e:
