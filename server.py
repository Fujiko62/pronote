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

def extract_surgical(html, username):
    """Extraction ultra-précise basée sur tes logs"""
    data = {
        'studentData': {'name': username.replace('.', ' ').title(), 'class': 'Détection...', 'average': 0, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'debug_info': {
            'html_size': len(html),
            'found_spans': 0,
            'raw_text_sample': html[:500]
        }
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. NOM (depuis le titre ou le header)
        title = soup.title.string if soup.title else ""
        if "-" in title:
            data['studentData']['name'] = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. EMPLOI DU TEMPS (Ton format exact !)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        data['debug_info']['found_spans'] = len(spans)
        
        for span in spans:
            text = span.get_text(" ").strip()
            # de 8h30 à 9h25 FRANCAIS
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })

        # 3. LA CLASSE (Recherche de motifs comme 3EME, 4EME...)
        class_match = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
        if class_match:
            data['studentData']['class'] = class_match.group(1)

    except Exception as e:
        logger.error(f"Error: {e}")
        data['debug_info']['error'] = str(e)
        
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
        callback = parse_qs(urlparse(res.url).query).get('callback', [''])[0]
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Rebond
        target = unquote(callback) if callback else url + "eleve.html"
        res_final = s.get(target, allow_redirects=True)
        
        # Securité redirection
        if "seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_surgical(res_final.text, u))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
