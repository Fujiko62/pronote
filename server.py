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

def extract_data(html, username):
    data = {
        'studentData': {'name': username.replace('.', ' ').title(), 'class': '3ème', 'average': 15},
        'schedule': [[], [], [], [], []], 'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True, 'raw_found': []
    }
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extraction Nom
    title = soup.title.string if soup.title else ""
    if "-" in title: data['studentData']['name'] = title.split('-')[1].strip()

    # Extraction Cours (ton format sr-only)
    day_idx = datetime.datetime.now().weekday()
    if day_idx > 4: day_idx = 0
    spans = soup.find_all('span', class_='sr-only')
    for span in spans:
        text = span.get_text().strip()
        m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
        if m:
            data['schedule'][day_idx].append({
                'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                'subject': m.group(3).strip(), 'teacher': "Prof", 'room': "Salle", 'color': 'bg-indigo-500'
            })
    return data

@app.route('/sync', methods=['POST'])
def sync():
    logs = []
    try:
        req = request.json
        u, p, url = req.get('username'), req.get('password'), req.get('schoolUrl')
        if not url.endswith('/'): url += '/'
        
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
        
        # 1. On va chercher le formulaire de l'ENT pour choper les jetons cachés
        logs.append("Phase 1 : Analyse du formulaire ENT...")
        res_page = s.get(url + "eleve.html", allow_redirects=True)
        login_url = res_page.url
        
        soup = BeautifulSoup(res_page.text, 'html.parser')
        form = soup.find('form')
        
        if not form:
            return jsonify({'error': 'Formulaire ENT introuvable', 'raw_found': [res_page.text[:1000]]}), 401
            
        # On récupère TOUS les champs cachés (CSRF, tokens, etc.)
        payload = {}
        for inp in form.find_all('input'):
            name = inp.get('name')
            if name: payload[name] = inp.get('value', '')
            
        # On remplit les identifiants (email ou username)
        if 'email' in payload: payload['email'] = u
        if 'username' in payload: payload['username'] = u
        payload['password'] = p
        
        # 2. Envoi du formulaire complet
        logs.append("Phase 2 : Envoi de l'authentification sécurisée...")
        action = form.get('action', 'https://ent.seine-et-marne.fr/auth/login')
        res_auth = s.post(action, data=payload, allow_redirects=True)
        
        # 3. Tentative de rebond vers Pronote
        logs.append("Phase 3 : Rebond vers Pronote...")
        res_final = s.get(url + "eleve.html", allow_redirects=True)
        
        if "identifiant=" in res_final.url:
            logs.append("✅ Succès ! Accès à Pronote validé.")
            return jsonify(extract_data(res_final.text, u))
        
        # Si on est tjs bloqué, on renvoie le HTML de la page d'erreur pour que je le lise
        return jsonify({
            'error': 'Bloqué sur le portail. Regardez les données brutes (icône 🐞).',
            'raw_found': [f"URL : {res_final.url}", f"HTML : {res_final.text[:2000]}"]
        }), 401

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
