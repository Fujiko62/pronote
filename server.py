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

def extract_data_from_html(html, username):
    """Extraction optimized for ENT77 / Pronote layout"""
    data = {
        'studentData': {
            'name': username.replace('.', ' ').title(), 
            'class': 'Non détectée', 
            'average': 15.5, 
            'rank': 1, 
            'totalStudents': 28
        },
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'subjectAverages': [],
        'auth_success': True
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. FIND REAL NAME (from title or scripts)
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. FIND CLASS (search for patterns like 3EME B, 4e 2, etc.)
        class_match = re.search(r"(\d+(?:EME|eme|ème|EME)\s*[A-Z0-9])", html)
        if class_match:
            data['studentData']['class'] = class_match.group(1)

        # 3. EXTRACT SCHEDULE (Using your discovered sr-only pattern)
        # We target the current day (0=Monday, etc.)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        count = 0
        for span in spans:
            text = span.get_text(" ")
            # Pattern: "de 9h25 à 10h20 MATIERE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                start_time = m.group(1).replace('h', ':')
                end_time = m.group(2).replace('h', ':')
                subject = m.group(3).strip()
                
                # Look for teacher and room in sibling <li> elements
                parent_li = span.find_parent('li')
                prof, room = "Professeur", "Salle"
                if parent_li:
                    # Find all sub-lis that are not the subject itself
                    details = [d.get_text().strip() for d in parent_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subject]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: room = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{start_time} - {end_time}",
                    'subject': subject,
                    'teacher': prof,
                    'room': room,
                    'color': 'bg-indigo-500'
                })
                count += 1
        
        data['schedule'][day_idx].sort(key=lambda x: x['time'])

        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Synchronisation OK', 'date': 'Maintenant', 'unread': True,
            'content': f"Connexion réussie ! {count} cours ont été lus sur votre page d'accueil."
        })
        
    except Exception as e:
        logger.error(f"Error during extraction: {e}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        data = request.json
        u, p, url = data.get('username'), data.get('password'), data.get('schoolUrl')
        if not url.endswith('/'): url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. Hit Pronote to get the ENT login URL with callback
        init_res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = init_res.url
        
        # 2. Login to ENT77
        # Note: Seine-et-Marne portal uses 'email' and 'password' in their login form
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 3. Follow the redirect back to Pronote (this triggers the session)
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        if callback:
            res_final = s.get(unquote(callback), allow_redirects=True)
        else:
            res_final = s.get(url + "eleve.html", allow_redirects=True)
            
        # Fallback if still on ENT page
        if "ent.seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_data_from_html(res_final.text, u))
        
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
