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

def extract_intelligent(html, username):
    # Fallback name
    name_display = username.replace('.', ' ').title()
    if '@' in name_display: name_display = name_display.split('@')[0]

    data = {
        'studentData': {
            'name': name_display, 
            'class': 'Classe détectée', 
            'average': 0, 'rank': 1, 'totalStudents': 30
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_spans': []
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. NOM (depuis le titre)
        title = soup.title.string if soup.title else ""
        if "-" in title:
            data['studentData']['name'] = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. EMPLOI DU TEMPS (le format que tu as trouvé !)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            data['raw_spans'].append(text) # Pour le debug
            
            # Format : de 8h30 à 9h25 FRANCAIS
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })

        # 3. CLASSE
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
        
        # 1. Login
        res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res.url
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Rebond
        target = unquote(callback) if callback else url + "eleve.html"
        res_final = s.get(target, allow_redirects=True)
        if "ent.seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_intelligent(res_final.text, u))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
