import os
import re
import json
import logging
import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import urlparse, parse_qs, unquote

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_surgical_data(html, username, url_reached):
    """Extraction finale des données une fois sur Pronote"""
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': '3ème', 'average': 15.0, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL finale : {url_reached}"]
    }

    try:
        # On évite à tout prix d'afficher "Collèges Connectés"
        if "Collèges Connectés" in html or "Portail" in html:
            data['auth_success'] = False
            return data

        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. NOM (depuis le titre ou header)
        title = soup.title.string if soup.title else ""
        if "-" in title and "PRONOTE" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name and len(extracted_name) > 3:
                data['studentData']['name'] = extracted_name

        # 2. EMPLOI DU TEMPS (ton format sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })
                data['raw_found'].append(f"Cours lu : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur extraction : {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    logs = []
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. On récupère le lien de login réel avec le callback Pronote
        logs.append("Phase 1 : Appel Pronote...")
        res_start = s.get(school_url + "eleve.html", allow_redirects=True)
        login_url = res_start.url
        
        # 2. On analyse la page de login de l'ENT pour trouver le formulaire
        logs.append(f"Phase 2 : Analyse du portail ENT77...")
        res_form = s.get(login_url)
        soup = BeautifulSoup(res_form.text, 'html.parser')
        
        # On cherche le champ email ou username
        user_field = "email"
        if soup.find('input', {'name': 'username'}): user_field = "username"
        
        # 3. Authentification réelle
        logs.append(f"Phase 3 : Envoi des identifiants ({user_field})...")
        payload = {user_field: u, 'password': p}
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        # 4. LE REBOND : On force l'accès à Pronote
        logs.append("Phase 4 : Rebond forcé vers Pronote...")
        # On retourne sur l'URL de départ, les cookies ENT vont nous laisser passer
        res_final = s.get(school_url + "eleve.html", allow_redirects=True)
        
        logs.append(f"URL finale : {res_final.url}")

        if "identifiant=" in res_final.url or "pronote" in res_final.url.lower():
            if len(res_final.text) > 5000: # On vérifie qu'on a bien chargé une vraie page
                result = extract_surgical_data(res_final.text, u, res_final.url)
                if result['auth_success']:
                    result['raw_found'] = logs + result['raw_found']
                    return jsonify(result)

        return jsonify({
            'error': 'Bloqué sur le portail ENT. Vérifiez vos identifiants ou réessayez.',
            'raw_found': logs + [f"URL d'arrêt : {res_final.url}", "Taille : " + str(len(res_final.text))]
        }), 401

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
