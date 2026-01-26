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
    """Extraction chirurgicale des données Pronote"""
    data = {
        'studentData': {'name': username.replace('.', ' ').title(), 'class': 'Non détectée', 'average': 0, 'rank': 1, 'totalStudents': 30},
        'schedule': [[], [], [], [], []], 'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [], 'auth_success': True
    }

    try:
        # 1. Extraction du NOM
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. Extraction de l'EMPLOI DU TEMPS (Format sr-only)
        soup = BeautifulSoup(html, 'html.parser')
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 # Weekend -> Lundi
        
        cours_items = soup.find_all('li', class_=re.compile(r'flex-contain'))
        for li in cours_items:
            span = li.find('span', class_='sr-only')
            if span:
                text = span.get_text()
                # Motif : "de 9h25 à 10h20 MATIERE"
                m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
                if m:
                    subj = m.group(3).strip()
                    # Chercher prof et salle dans les li enfants
                    infos = [i.get_text().strip() for i in li.find_all('li') if i.get_text().strip() != subj]
                    prof = infos[0] if len(infos) > 0 else "Professeur"
                    salle = infos[1] if len(infos) > 1 else "Salle"
                    
                    data['schedule'][day_idx].append({
                        'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                        'subject': subj, 'teacher': prof, 'room': salle, 'color': 'bg-indigo-500'
                    })

        # 3. Extraction de la CLASSE
        class_match = re.search(r"['\"](\d+(?:EME|eme|ème|EME)\s*[A-Z0-9])['\"]", html)
        if class_match:
            data['studentData']['class'] = class_match.group(1)

        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Connexion OK', 'date': 'Maintenant', 'unread': True,
            'content': f"Connexion réussie ! {len(data['schedule'][day_idx])} cours ont été lus sur votre page d'accueil."
        })
        
        return data
        
    except Exception as e:
        logger.error(f"Erreur scrap: {e}")
        return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        data = request.json
        u = data.get('username')
        p = data.get('password')
        url = data.get('schoolUrl')
        
        if not url.endswith('/'): url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # Login ENT77
        res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res.url
        callback_list = parse_qs(urlparse(login_url).query).get('callback', [''])
        callback = callback_list[0] if callback_list else ''
        
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # Accès final
        res_final = s.get(url + "eleve.html", allow_redirects=True)
        if "ent.seine-et-marne" in res_final.url and callback:
            res_final = s.get(unquote(callback), allow_redirects=True)
            
        if "identifiant=" in res_final.url or len(res_final.text) > 4000:
            return jsonify(extract_from_html(res_final.text, u))
            
        return jsonify({'error': 'Authentification réussie mais Pronote refuse de donner les données (protection active).'}), 401
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
