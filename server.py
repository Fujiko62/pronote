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
    """Extraction finale des données depuis Pronote"""
    # Formater le nom depuis l'identifiant (hippolyte.bruneau -> Hippolyte Bruneau)
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {'name': display_name, 'class': '3ème', 'average': 15.2, 'rank': 1},
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL atteinte : {url_reached}", f"Taille HTML : {len(html)} octets"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du NOM RÉEL dans le titre
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title and "-" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name: data['studentData']['name'] = extracted_name

        # 2. Extraction de la CLASSE
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. Extraction de l'EMPLOI DU TEMPS (Ton format sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            # de 9h25 à 10h20 MATIERE
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': "Professeur", 'room': "Salle", 'color': 'bg-indigo-500'
                })
                data['raw_found'].append(f"Cours trouvé : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur d'extraction : {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    logs = []
    try:
        req = request.json
        u, p, school_url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not school_url.endswith('/'): school_url += '/'
        
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        })
        
        # 1. On va sur Pronote pour déclencher la redirection CAS et choper le CALLBACK
        logs.append("Initialisation : Récupération du ticket de sécurité...")
        res_init = s.get(school_url + "eleve.html", allow_redirects=True)
        
        # On extrait l'URL de retour (callback) vers le serveur CAS de ton école
        parsed_url = urlparse(res_init.url)
        callback = parse_qs(parsed_url.query).get('callback', [None])[0]
        
        if not callback:
            logs.append("⚠️ Lien de retour Pronote introuvable (Peut-être déjà connecté?)")
            # On tente l'accès direct au cas où
            res_final = s.get(school_url + "eleve.html", allow_redirects=True)
        else:
            # 2. On se connecte à l'ENT
            logs.append("Authentification sur le portail ENT77...")
            payload = {'email': u, 'password': p}
            s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
            
            # 3. LE REBOND : On suit manuellement le lien de retour Pronote
            logs.append("Déverrouillage de l'accès Pronote...")
            res_final = s.get(unquote(callback), allow_redirects=True)
            
            # Si on est tjs bloqué, on tente l'URL d'origine
            if "index-education.net" not in res_final.url:
                logs.append("Rebond secondaire vers le serveur de l'école...")
                res_final = s.get(school_url + "eleve.html", allow_redirects=True)

        logs.append(f"Page atteinte : {res_final.url}")

        # 4. Extraction finale
        if "identifiant=" in res_final.url or "pronote" in res_final.url.lower():
            result = extract_surgical_data(res_final.text, u, res_final.url)
            result['raw_found'] = logs + result['raw_found']
            return jsonify(result)
        else:
            return jsonify({
                'error': 'Le portail ENT refuse de nous envoyer vers Pronote.',
                'raw_found': logs + [f"URL d'arrêt : {res_final.url}", "HTML court : " + res_final.text[:500]]
            }), 401

    except Exception as e:
        return jsonify({'error': str(e), 'raw_found': logs}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
