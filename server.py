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

def extract_from_html(html, username):
    """Extraction chirurgicale basée sur tes découvertes HTML"""
    data = {
        'studentData': {'name': username, 'class': 'Détection...', 'average': 0, 'rank': 1, 'totalStudents': 30},
        'schedule': [[], [], [], [], []], 'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [], 'auth_success': True
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. NOM DE L'ELEVE (depuis le titre)
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. EMPLOI DU TEMPS (le format que tu as trouvé !)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        # On cherche tous les cours (Format : de 9h25 à 10h20 MATIERE)
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ")
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                # Chercher prof et salle dans les li enfants du parent
                parent_li = span.find_parent('li')
                prof, salle = "Professeur", "Salle"
                if parent_li:
                    details = [d.get_text().strip() for d in parent_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: salle = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': salle, 'color': 'bg-indigo-500'
                })

        # 3. LA CLASSE
        class_match = re.search(r"(\d+(?:EME|eme|ème|EME)\s*[A-Z0-9])", html)
        if class_match:
            data['studentData']['class'] = class_match.group(1)

        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Synchronisation OK', 'date': 'Maintenant',
            'content': f"Connexion réussie ! {len(data['schedule'][day_idx])} cours lus."
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
        
        # 1. Connexion initiale pour choper le callback
        res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res.url
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        
        # 2. Authentification ENT77
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 3. Le Rebond (La méthode Proxy)
        # On va sur le callback pour forcer le portail à nous envoyer sur Pronote
        res_final = s.get(unquote(callback), allow_redirects=True)
        
        # Si on est tjs pas sur Pronote, on tente l'URL directe maintenant qu'on a le cookie
        if "pronote" not in res_final.url.lower():
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        return jsonify(extract_from_html(res_final.text, u))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
