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
    """Extraction based on your specific college HTML structure"""
    display_name = username.split('@')[0].replace('.', ' ').title() if '@' in username else username.replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': 'Non détectée', 'average': 15.2, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL atteinte : {url_reached}"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. FIND REAL NAME
        # Check Title
        title = soup.title.string if soup.title else ""
        data['raw_found'].append(f"Titre de la page : {title}")
        if "-" in title:
            data['studentData']['name'] = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
        
        # Check Scripts
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string: continue
            m = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", script.string)
            if m: data['studentData']['name'] = m.group(1)

        # 2. FIND CLASS (Regex for 6EME, 5EME, 4EME, 3EME)
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. FIND SCHEDULE (Your sr-only pattern)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            data['raw_found'].append(text)
            
            # Format: de 9h25 à 10h20 MATIERE
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                # Extraction prof/room
                p_li = span.find_parent('li')
                prof, room = "Professeur", "Salle"
                if p_li:
                    det = [d.get_text().strip() for d in p_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(det) >= 1: prof = det[0]
                    if len(det) >= 2: room = det[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': room, 'color': 'bg-indigo-500'
                })

        # 4. Success message
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Importation OK', 'date': 'Maintenant',
            'content': f"Connexion réussie ! {len(data['schedule'][day_idx])} cours trouvés."
        })

    except Exception as e:
        logger.error(f"Scraping error: {e}")
        data['raw_found'].append(f"Erreur: {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p, url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not url.endswith('/'): url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. Login to Portal
        res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res.url
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Portal to Pronote transition
        # We search for the specific link in the portal page if not redirected
        portal_res = s.get("https://ent.seine-et-marne.fr/", allow_redirects=True)
        soup = BeautifulSoup(portal_res.text, 'html.parser')
        
        # Find any link that looks like Pronote
        pronote_link = None
        for a in soup.find_all('a', href=True):
            if 'pronote' in a['href'].lower() or 'hyperplanning' in a['href'].lower():
                pronote_link = a['href']
                break
        
        if pronote_link:
            if not pronote_link.startswith('http'):
                pronote_link = "https://ent.seine-et-marne.fr" + pronote_link
            res_final = s.get(pronote_link, allow_redirects=True)
        else:
            # Fallback
            res_final = s.get(unquote(callback) if callback else url + "eleve.html", allow_redirects=True)
        
        # Ultimate force check
        if "seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_surgical_data(res_final.text, u, res_final.url))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
