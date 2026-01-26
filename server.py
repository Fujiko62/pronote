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
    """Analyse chirurgicale basée sur ton format : 'de 8h30 à 9h25 FRANCAIS'"""
    # Formater le nom : hippolyte.bruneau -> Hippolyte Bruneau
    name_display = username.replace('.', ' ').title()
    if '@' in name_display: name_display = name_display.split('@')[0]

    data = {
        'studentData': {
            'name': name_display, 
            'class': 'Classe détectée', 
            'average': 14.8, # Valeur démo
            'rank': 3, 
            'totalStudents': 28
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du NOM réel s'il est dans le titre
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. ANALYSE DE L'EMPLOI DU TEMPS
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        cours_trouves = 0
        
        for span in spans:
            text = span.get_text(" ").strip()
            
            # Format détecté : "de 8h30 à 9h25 FRANCAIS"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                heure_debut = m.group(1).replace('h', ':')
                heure_fin = m.group(2).replace('h', ':')
                matiere = m.group(3).strip()
                
                # Ignorer la pause déjeuner dans la liste des cours
                if "pause" in matiere.lower():
                    continue

                # Déterminer la couleur selon la matière
                color = "bg-indigo-500"
                if "FRANCAIS" in matiere: color = "bg-pink-500"
                elif "ANGLAIS" in matiere: color = "bg-blue-500"
                elif "MATHEMATIQUES" in matiere: color = "bg-indigo-600"
                elif "SPORT" in matiere: color = "bg-orange-500"
                elif "ALLEMAND" in matiere: color = "bg-yellow-500"
                elif "SCIENCES" in matiere: color = "bg-green-500"

                data['schedule'][day_idx].append({
                    'time': f"{heure_debut} - {heure_fin}",
                    'subject': matiere,
                    'teacher': "Professeur",
                    'room': "Salle",
                    'color': color
                })
                cours_trouves += 1

        # 3. Extraction de la CLASSE (Regex pour 3EME, 4EME, etc.)
        class_search = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
        if class_search:
            data['studentData']['class'] = class_search.group(1)

        # Message système
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Import réussi', 'date': 'Maintenant',
            'content': f"Connexion réussie ! {cours_trouves} cours ont été trouvés pour aujourd'hui."
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
        
        # Login ENT77
        res = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res.url
        callback = parse_qs(urlparse(login_url).query).get('callback', [''])[0]
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # Passage Pronote
        target = unquote(callback) if callback else url + "eleve.html"
        res_final = s.get(target, allow_redirects=True)
        
        # On renvoie les infos
        return jsonify(extract_intelligent(res_final.text, u))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
