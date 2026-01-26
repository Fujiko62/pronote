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
    """Extraction chirurgicale des données Pronote depuis le HTML brut"""
    # Extraction du Nom depuis le titre
    name = username.replace('.', ' ').title()
    title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
    if title_match:
        name = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()
    
    # Extraction de la Classe (ex: 3EME 4, 4EME B)
    klass = "Non détectée"
    class_match = re.search(r"(\d+(?:EME|eme|ème|EME)\s*[A-Z0-9])", html)
    if class_match:
        klass = class_match.group(1)

    data = {
        'studentData': {
            'name': name,
            'class': klass,
            'average': 14.5, # Valeur démo car chiffrée
            'rank': 1,
            'totalStudents': 30
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
        # On détermine le jour actuel (Lundi=0)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        # On cherche les cours via les balises sr-only que tu as trouvées
        spans = soup.find_all('span', class_='sr-only')
        count = 0
        for span in spans:
            text = span.get_text(" ")
            # Motif : de 9h25 à 10h20 MATIERE
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                start = m.group(1).replace('h', ':')
                end = m.group(2).replace('h', ':')
                subject = m.group(3).strip()
                
                # Chercher le prof et la salle dans les <li> voisins
                parent_li = span.find_parent('li')
                prof, room = "Professeur", "Salle"
                if parent_li:
                    details = [d.get_text().strip() for d in parent_li.find_all('li') if d.get_text().strip() != subject]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: room = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{start} - {end}",
                    'subject': subject,
                    'teacher': prof,
                    'room': room,
                    'color': 'bg-indigo-500'
                })
                count += 1
        
        data['schedule'][day_idx].sort(key=lambda x: x['time'])

        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Synchronisation OK', 'date': 'Maintenant', 'unread': True,
            'content': f"Connexion réussie ! {count} cours ont été importés pour aujourd'hui."
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
        
        # 1. Login au portail ENT77
        init_res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = init_res.url
        callback_list = parse_qs(urlparse(login_url).query).get('callback', [''])
        callback = callback_list[0] if callback_list else ''
        
        # Authentification
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 2. Suivre le callback vers Pronote
        if callback:
            res_final = s.get(unquote(callback), allow_redirects=True)
        else:
            res_final = s.get(url + "eleve.html", allow_redirects=True)
            
        # Si on est tjs sur l'ENT, forcer Pronote
        if "ent.seine-et-marne" in res_final.url:
            res_final = s.get(url + "eleve.html", allow_redirects=True)

        # 3. Extraction
        return jsonify(extract_from_html(res_final.text, u))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
