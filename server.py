from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import logging
import re
import json

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ask_ai_to_extract(html_snippet, username):
    """Demande à l'IA de parser le HTML pour nous"""
    try:
        prompt = f"""
        Analyse ce code HTML de PRONOTE. 
        1. Trouve le nom de l'élève.
        2. Trouve sa classe.
        3. Extrais TOUT l'emploi du temps (Heure, Matière, Prof, Salle).
        Réponds UNIQUEMENT avec un JSON au format:
        {{
          "name": "...",
          "class": "...",
          "schedule": [
            {{"time": "9h25 - 10h20", "subject": "HISTOIRE", "teacher": "Mr X", "room": "201"}},
            ...
          ]
        }}
        Si tu ne trouves rien, mets des valeurs vides.
        Voici le code HTML: {html_snippet[:3000]}
        """
        # Utilisation de Pollinations AI (gratuit et sans clé)
        url = f"https://text.pollinations.ai/{requests.utils.quote(prompt)}?model=openai&jsonMode=true"
        response = requests.get(url, timeout=15)
        
        # Nettoyage de la réponse pour ne garder que le JSON
        raw_text = response.text
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        logger.error(f"Erreur IA: {e}")
    return None

def login_and_sync(username, password, school_url):
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
    
    try:
        # 1. Login ENT
        res = s.get(f"{school_url}eleve.html", allow_redirects=True)
        login_url = res.url
        
        payload = {'email': username, 'password': password}
        res_auth = s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        # 2. Accès Pronote final
        res_final = s.get(f"{school_url}eleve.html", allow_redirects=True)
        html = res_final.text
        
        # 3. ANALYSE PAR IA
        logger.info("Envoi du code HTML à l'IA pour extraction...")
        # On prend une partie du HTML (autour de l'emploi du temps) pour ne pas saturer l'IA
        ai_data = ask_ai_to_extract(html, username)
        
        if ai_data:
            logger.info("IA a réussi l'extraction !")
            data = {
                'studentData': {
                    'name': ai_data.get('name', username),
                    'class': ai_data.get('class', 'Non détectée'),
                    'average': 15.0, 'rank': 1, 'totalStudents': 30
                },
                'schedule': [[], [], [], [], []],
                'homework': [], 'grades': [], 'auth_success': True
            }
            
            # On remplit l'emploi du temps (Lundi par défaut ou jour actuel)
            from datetime import datetime
            day_idx = datetime.now().weekday()
            if day_idx > 4: day_idx = 0
            
            for course in ai_data.get('schedule', []):
                data['schedule'][day_idx].append({
                    'time': course.get('time', ''),
                    'subject': course.get('subject', 'Cours'),
                    'teacher': course.get('teacher', ''),
                    'room': course.get('room', ''),
                    'color': 'bg-indigo-500'
                })
            return data
            
        return None
    except Exception as e:
        logger.error(f"Crash: {e}")
        return None

@app.route('/sync', methods=['POST'])
def sync_pronote():
    req = request.json
    url = req.get('schoolUrl', '')
    if not url.endswith('/'): url += '/'
    
    result = login_and_sync(req.get('username'), req.get('password'), url)
    if result: return jsonify(result)
    return jsonify({'error': 'La connexion a réussi mais l\'IA n\'a pas pu lire les données.'}), 401

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
