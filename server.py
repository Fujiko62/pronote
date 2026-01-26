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
    """Extraction finale ultra-robuste depuis le HTML de Pronote"""
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': 'Non détectée', 'average': 15.2, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL finale : {url_reached}", f"Taille HTML : {len(html)}"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du NOM RÉEL
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title and "-" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name: data['studentData']['name'] = extracted_name
        
        # On cherche aussi dans les variables JS
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string: continue
            m = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", script.string)
            if m: data['studentData']['name'] = m.group(1)

        # 2. Extraction de la CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. Extraction de l'EMPLOI DU TEMPS (Ton format sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            # Format: de 9h25 à 10h20 MATIERE
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })
                data['raw_found'].append(f"Cours trouvé : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur d'extraction : {str(e)}")
        
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
        logs.append("Connexion au portail ENT77...")
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Recherche du lien Pronote sur le portail
        logs.append("Recherche de l'icône Pronote dans vos applications...")
        portal_page = s.get("https://ent.seine-et-marne.fr/", allow_redirects=True)
        soup = BeautifulSoup(portal_page.text, 'html.parser')
        
        pronote_link = None
        # On cherche tous les liens qui pointent vers le service CAS de Pronote
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'pronote' in href or 'cas/login' in href:
                pronote_link = a['href']
                break
        
        # 3. Navigation vers Pronote
        if pronote_link:
            logs.append(f"Lancement de l'application Pronote...")
            if not pronote_link.startswith('http'):
                pronote_link = "https://ent.seine-et-marne.fr" + pronote_link
            res_final = s.get(pronote_link, allow_redirects=True)
        else:
            logs.append("Lien direct introuvable, tentative par rebond standard...")
            # Fallback vers l'URL directe de votre collège
            res_final = s.get(school_url + "eleve.html", allow_redirects=True)
        
        # 4. Vérification de sécurité (si encore sur l'ENT, on force)
        if "seine-et-marne.fr" in res_final.url:
            logs.append("Redirection forcée vers le serveur de l'école...")
            res_final = s.get(school_url + "eleve.html", allow_redirects=True)

        logs.append(f"Page atteinte : {res_final.url}")

        # 5. Extraction et renvoi des données
        result = extract_surgical_data(res_final.text, u, res_final.url)
        result['raw_found'] = logs + result['raw_found']
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
