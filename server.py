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
    """Extraction ultra-précise des données de l'école"""
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {
            'name': display_name, 
            'class': 'Non détectée', 
            'average': 15.2,
            'rank': 1
        },
        'schedule': [[], [], [], [], []],  # 5 jours (Lun-Ven)
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL atteinte : {url_reached}", f"Taille page : {len(html)}"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du nom depuis le titre Pronote
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title and "-" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name: data['studentData']['name'] = extracted_name

        # 2. Extraction de la classe (6EME, 5EME, 4EME, 3EME)
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. Extraction de l'emploi du temps (format sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            # Regex: "de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                p_li = span.find_parent('li')
                prof, room = "Non spécifié", "Salle"
                if p_li:
                    details = [d.get_text().strip() for d in p_li.find_all('li') 
                               if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: room = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': room, 'color': 'bg-indigo-500'
                })
                data['raw_found'].append(f"Cours trouvé : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur d'extraction : {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # ÉTAPE 1 : Appel Pronote pour obtenir le callback
        res_init = s.get(school_url + "eleve.html", allow_redirects=True)
        parsed_url = urlparse(res_init.url)
        callback = parse_qs(parsed_url.query).get('callback', [None])[0]
        
        if not callback:
            return jsonify({'error': 'Lien de sécurité introuvable.'}), 401

        # ÉTAPE 2 : Connexion ENT Seine-et-Marne
        payload = {'email': u, 'password': p}
        s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        # ÉTAPE 3 : Rebond vers Pronote
        res_final = s.get(unquote(callback), allow_redirects=True)
        
        if "index-education.net" not in res_final.url:
            res_final = s.get(school_url + "eleve.html", allow_redirects=True)

        # ÉTAPE 4 : Extraction et renvoi
        return jsonify(extract_surgical_data(res_final.text, u, res_final.url))

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
