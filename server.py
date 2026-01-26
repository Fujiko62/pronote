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

def extract_surgical_data(html, username, url):
    """Parses the final Pronote page using the sr-only pattern you found"""
    data = {
        'studentData': {'name': username, 'class': '3ème', 'average': 15},
        'schedule': [[], [], [], [], []], 'homework': [], 'grades': [], 
        'messages': [], 'subjectAverages': [], 'auth_success': True, 'raw_found': []
    }
    
    # Extract Name from Title
    title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
    if title_match:
        data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

    # Extract Schedule (The specific pattern you discovered)
    soup = BeautifulSoup(html, 'html.parser')
    day_idx = datetime.datetime.now().weekday()
    if day_idx > 4: day_idx = 0
    
    spans = soup.find_all('span', class_='sr-only')
    for span in spans:
        text = span.get_text().strip()
        data['raw_found'].append(text)
        m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
        if m:
            subj = m.group(3).strip()
            if "pause" in subj.lower(): continue
            data['schedule'][day_idx].append({
                'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
            })
    
    # Extract Class
    class_m = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
    if class_m: data['studentData']['class'] = class_m.group(1)
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    logs = []
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        # 1. SETUP SESSION
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded'
        })

        # 2. STEP 1: Get the login page and the callback URL
        logs.append("Initialisation du canal sécurisé...")
        res_init = s.get(school_url + "eleve.html", allow_redirects=True)
        login_url = res_init.url # This is the ENT login page
        
        # Extract the CAS callback (the secret link to go back to Pronote)
        parsed = urlparse(login_url)
        callback = parse_qs(parsed.query).get('callback', [None])[0]
        
        # 3. STEP 2: Perform the Authentication on ENT77
        logs.append("Authentification ENT en cours...")
        payload = { 'email': u, 'password': p }
        
        # We MUST post to the correct auth endpoint
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        # 4. STEP 3: Manual Rebound to the CAS Service
        # This is the "Proxy" trick. We visit the callback link after being logged in.
        if callback:
            logs.append("Déverrouillage de l'accès Pronote...")
            res_pronote = s.get(unquote(callback), allow_redirects=True)
        else:
            res_pronote = s.get(school_url + "eleve.html", allow_redirects=True)

        logs.append(f"Arrivée sur : {res_pronote.url}")

        # 5. VERIFY AND EXTRACT
        if "identifiant=" in res_pronote.url or "pronote" in res_pronote.url.lower():
            logs.append("✅ Porte ouverte ! Lecture des données...")
            result = extract_surgical_data(res_pronote.text, u, res_pronote.url)
            result['raw_found'] = logs + result['raw_found']
            return jsonify(result)
        
        return jsonify({
            'error': 'Le portail ENT ne nous a pas redirigé vers Pronote.',
            'raw_found': logs + [f"URL finale : {res_pronote.url}", "HTML : " + res_pronote.text[:500]]
        }), 401

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
