import os
import re
import json
import logging
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import urlparse, parse_qs, unquote

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_data_from_html(html, username):
    """Extraction des données depuis le code HTML de Pronote"""
    data = {
        'studentData': {
            'name': username.replace('.', ' ').title(), 
            'class': 'Non détectée', 
            'average': 0, 'rank': 1, 'totalStudents': 30
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du NOM RÉEL
        # On cherche dans le titre : PRONOTE - NOM Prénom - ESPACE ÉLÈVE
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. Extraction de la CLASSE
        # On cherche des motifs comme "3EME 4" ou "4EME B"
        class_match = re.search(r"(\d+(?:EME|eme|ème|EME)\s*[A-Z0-9])", html)
        if class_match:
            data['studentData']['class'] = class_match.group(1)

        # 3. Extraction de l'EMPLOI DU TEMPS (Format sr-only détecté)
        day_idx = datetime.now().weekday()
        if day_idx > 4: day_idx = 0 # Lundi si weekend
        
        spans = soup.find_all('span', class_='sr-only')
        count = 0
        for span in spans:
            text = span.get_text(" ")
            # Format : "de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                # On cherche le prof et la salle dans les <li> voisins du parent
                parent_li = span.find_parent('li')
                prof, salle = "Professeur", "Salle"
                if parent_li:
                    details = [d.get_text().strip() for d in parent_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: salle = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': salle, 'color': 'bg-indigo-500'
                })
                count += 1
        
        data['schedule'][day_idx].sort(key=lambda x: x['time'])
        
        if count > 0:
            data['messages'].append({
                'id': 1, 'from': 'Système', 'subject': 'Synchronisation OK', 'date': 'Maintenant',
                'content': f"Connexion réussie ! {count} cours ont été lus sur votre page d'accueil."
            })
            
    except Exception as e:
        logger.error(f"Erreur scrap: {e}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p, url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not url.endswith('/'): url += '/'
        
        s = requests.Session()
        # On imite un navigateur moderne
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9'
        })
        
        # 1. Accès Pronote pour récupérer l'URL de redirection CAS
        logger.info(f"Étape 1 : Accès Pronote {url}")
        res = s.get(url + "eleve.html", allow_redirects=True)
        
        # On extrait le 'service' qui est l'URL de retour après le login
        parsed_url = urlparse(res.url)
        params = parse_qs(parsed_url.query)
        service_url = params.get('service', [None])[0]
        
        # 2. Login à l'ENT
        logger.info("Étape 2 : Authentification ENT Seine-et-Marne")
        # On poste sur l'URL de login de l'ENT
        login_data = {'email': u, 'password': p}
        # On utilise l'URL de login du portail
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data=login_data, allow_redirects=True)
        
        # 3. Accès à Pronote via le service CAS
        # C'est l'étape où on "clique" sur l'application
        logger.info("Étape 3 : Passage du portail vers Pronote")
        if service_url:
            res_final = s.get(unquote(service_url), allow_redirects=True)
        else:
            res_final = s.get(url + "eleve.html", allow_redirects=True)
            
        # Si on est toujours sur l'ENT (portail d'icônes), on force l'URL Pronote
        if "ent.seine-et-marne" in res_final.url:
            logger.info("Redirection manuelle car coincé sur le portail...")
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        logger.info(f"Arrivée finale : {res_final.url}")
        
        # 4. Extraction des données
        return jsonify(extract_data_from_html(res_final.text, u))
        
    except Exception as e:
        logger.error(f"Erreur globale : {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
