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
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': 'Classe non détectée', 'average': 15.2, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL finale : {url_reached}", f"Taille HTML : {len(html)}"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. NOM (Titre)
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title and "-" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name: data['studentData']['name'] = extracted_name

        # 2. CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. EMPLOI DU TEMPS
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
                data['raw_found'].append(f"Cours : {subj}")

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
        
        # 1. Login au portail ENT77
        logs.append("Phase 1 : Authentification sur le portail...")
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. On est sur le portail, on cherche Pronote
        logs.append("Phase 2 : Recherche de l'application Pronote...")
        portal = s.get("https://ent.seine-et-marne.fr/", allow_redirects=True)
        soup = BeautifulSoup(portal.text, 'html.parser')
        
        # On cherche un lien qui contient "pronote" ou "index-education"
        pronote_link = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            if "pronote" in href.lower() or "index-education" in href.lower():
                pronote_link = href
                if not pronote_link.startswith('http'):
                    pronote_link = "https://ent.seine-et-marne.fr" + pronote_link
                break
        
        # 3. Clic sur le lien ou Rebond standard
        if pronote_link:
            logs.append(f"Phase 3 : Clic sur le lien trouvé : {pronote_link}")
            res_final = s.get(pronote_link, allow_redirects=True)
        else:
            logs.append("Phase 3 : Lien introuvable, tentative de rebond standard...")
            # On tente de forcer l'accès via le CAS
            cas_url = f"https://ent77.seine-et-marne.fr/cas/login?service={requests.utils.quote(school_url + 'eleve.html')}"
            res_final = s.get(cas_url, allow_redirects=True)

        logs.append(f"Page finale : {res_final.url}")

        # 4. Vérification et extraction
        if "identifiant=" in res_final.url or "pronote" in res_final.url.lower():
            result = extract_surgical_data(res_final.text, u, res_final.url)
            result['raw_found'] = logs + result['raw_found']
            return jsonify(result)
        else:
            return jsonify({
                'error': 'Connexion réussie à l\'ENT, mais impossible d\'entrer dans Pronote.',
                'raw_found': logs + [f"URL d'arrêt : {res_final.url}", f"Taille HTML : {len(res_final.text)}"]
            }), 401

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
