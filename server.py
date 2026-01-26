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

def extract_surgical_data(html, username):
    """Extraction basée sur tes découvertes réelles dans le code de ton collège"""
    data = {
        'studentData': {
            'name': username.replace('.', ' ').title(), 
            'class': 'Classe inconnue', 
            'average': 0
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [] # Pour le bouton debug
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du NOM (depuis le titre de la page)
        title = soup.title.string if soup.title else ""
        if "-" in title:
            data['studentData']['name'] = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. Extraction de l'EMPLOI DU TEMPS (ton format !)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        # On cherche tous les spans sr-only
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            data['raw_found'].append(text)
            
            # Format détecté : "de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                # On cherche le prof et la salle (souvent les <li> suivants)
                parent_li = span.find_parent('li')
                prof, room = "Professeur", "Salle"
                if parent_li:
                    details = [d.get_text().strip() for d in parent_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: room = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': room, 'color': 'bg-indigo-500'
                })

        # 3. Extraction de la CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1)

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
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. Login au portail
        res = s.get(url + "eleve.html", allow_redirects=True)
        callback = parse_qs(urlparse(res.url).query).get('callback', [''])[0]
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Rebond Pronote
        res_final = s.get(unquote(callback) if callback else url + "eleve.html", allow_redirects=True)
        if "ent.seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_surgical_data(res_final.text, u))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
