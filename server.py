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

def extract_real_data(html, username, url):
    """Extraction finale une fois dans Pronote"""
    data = {
        'studentData': {'name': username, 'class': 'Classe non détectée', 'average': 0},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL finale : {url}", f"Taille HTML : {len(html)}"]
    }

    try:
        # 1. Extraction du NOM
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. Extraction de l'EMPLOI DU TEMPS
        soup = BeautifulSoup(html, 'html.parser')
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            data['raw_found'].append(text)
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })

        # 3. Extraction de la CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|A|B|C|D))\b", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1)

    except Exception as e:
        logger.error(f"Error parse: {e}")
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. On va sur Pronote -> On récupère l'URL de rebond CAS
        res = s.get(school_url + "eleve.html", allow_redirects=True)
        # URL de type : https://ent.seine-et-marne.fr?callback=https://ent77.seine-et-marne.fr/cas/login?service=...
        
        parsed_init = urlparse(res.url)
        callback_url = parse_qs(parsed_init.query).get('callback', [None])[0]
        
        if not callback_url:
            return jsonify({'error': 'Impossible de trouver le lien de connexion ENT.'}), 401
            
        # 2. Authentification ENT
        # Le portail ENT77 demande un login sur /auth/login
        s.post("https://ent.seine-et-marne.fr/auth/login", data={'email': u, 'password': p}, allow_redirects=True)
        
        # 3. LA CLE DU PROBLEME : Suivre le lien de rebond CAS
        # C'est cette URL qui génère le ticket de session pour Pronote
        res_cas = s.get(unquote(callback_url), allow_redirects=True)
        
        # 4. Maintenant on recharge la page Pronote finale
        # Normalement s.get(res_cas.url) nous emmène sur Pronote avec un cookie valide
        res_final = s.get(school_url + "eleve.html", allow_redirects=True)
        
        logger.info(f"Navigation terminee sur : {res_final.url}")
        
        # Si on est toujours sur l'ENT, c'est que les identifiants sont faux ou session bloquée
        if "seine-et-marne.fr" in res_final.url:
            return jsonify({
                'error': 'Connexion au portail réussie, mais Pronote refuse l\'accès (Vérifiez votre mot de passe).',
                'raw_found': [f"URL Finale : {res_final.url}", "Le serveur est resté bloqué sur le portail ENT."]
            }), 401

        return jsonify(extract_real_data(res_final.text, u, res_final.url))

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
