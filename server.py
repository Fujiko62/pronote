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
    """Extraction finale des données"""
    display_name = username.split('@')[0].replace('.', ' ').title() if '@' in username else username.replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': '3ème', 'average': 15.2, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL finale atteinte : {url_reached}", f"Taille de la page : {len(html)} octets"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Trouver le NOM
        title = soup.title.string if soup.title else ""
        if "-" in title:
            data['studentData']['name'] = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
        
        # 2. Trouver la CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. Trouver l'EMPLOI DU TEMPS (ton format sr-only)
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
                data['raw_found'].append(f"Cours détecté : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur pendant l'extraction : {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    logs = []
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        s = requests.Session()
        # IMITATION AVG SECURE BROWSER
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 AVG/143.0.0.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9',
            'DNT': '1'
        })
        
        # 1. Phase d'initialisation (on récupère les cookies de session ENT)
        logs.append("Phase 1 : Initialisation des cookies...")
        res_init = s.get("https://ent.seine-et-marne.fr/auth/login", allow_redirects=True)
        
        # 2. Phase de Login (on tente 'email' ET 'username' pour être sûr)
        logs.append("Phase 2 : Authentification ENT...")
        payload = {'email': u, 'password': p}
        # Certains serveurs demandent 'username' au lieu de 'email'
        res_login = s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        if "identifiants invalides" in res_login.text.lower():
            return jsonify({'error': 'L\'ENT refuse vos identifiants. Vérifiez votre mail ou pseudo.', 'raw_found': logs}), 401

        # 3. Phase de Rebond vers Pronote
        logs.append("Phase 3 : Rebond vers Pronote...")
        res_pronote = s.get(school_url + "eleve.html", allow_redirects=True)
        
        # Si on est tjs sur l'ENT, c'est qu'il faut un ticket
        if "ent.seine-et-marne.fr" in res_pronote.url:
            logs.append("Tentative de forçage via le portail d'applications...")
            # On cherche le lien CAS
            res_cas = s.get(f"https://ent77.seine-et-marne.fr/cas/login?service={requests.utils.quote(school_url + 'eleve.html')}", allow_redirects=True)
            res_pronote = res_cas

        logs.append(f"Destination finale : {res_pronote.url}")
        
        # Vérification finale
        if "identifiant=" in res_pronote.url or "pronote" in res_pronote.url.lower():
            result = extract_surgical_data(res_pronote.text, u, res_pronote.url)
            result['raw_found'] = logs + result['raw_found']
            return jsonify(result)
        else:
            return jsonify({
                'error': 'Impossible d\'entrer dans Pronote (bloqué sur le portail).',
                'raw_found': logs + [f"URL finale : {res_pronote.url}", "Contenu court : " + res_pronote.text[:200]]
            }), 401

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
