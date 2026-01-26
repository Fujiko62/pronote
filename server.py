import os
import re
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

def extract_from_html(html, username):
    """Extraction basée sur tes découvertes : 'de 8h30 à 9h25 FRANCAIS'"""
    # On prépare la structure
    data = {
        'studentData': {
            'name': username.replace('.', ' ').title(), 
            'class': 'Non détectée', 
            'average': 15.0, # Valeur démo car chiffrée
            'rank': 1
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'debug_raw': [] # Pour voir ce qu'on a lu
    }

    try:
        # 1. NOM DE L'ELEVE (depuis le titre)
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. EMPLOI DU TEMPS
        soup = BeautifulSoup(html, 'html.parser')
        # On cible le jour actuel
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            data['debug_raw'].append(text)
            
            # Format : de 8h30 à 9h25 FRANCAIS
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue

                # Extraction prof/salle
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

        # 3. CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1)

        # Message de confirmation
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Extraction réussie', 'date': 'Maintenant',
            'content': f"Succès ! {len(data['schedule'][day_idx])} cours ont été lus."
        })
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
        
        # 1. Obtenir le lien de login ENT
        init = s.get(url + "eleve.html", allow_redirects=True)
        login_url = init.url
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        
        # 2. Login ENT77
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 3. Rebond vers Pronote
        res_final = s.get(unquote(callback) if callback else url + "eleve.html", allow_redirects=True)
        
        # Si tjs sur l'ENT, forcer l'accès
        if "seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_from_html(res_final.text, u))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
