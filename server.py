from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
import logging
import re
import json
import datetime

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_pronote_clone(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 AVG/143.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    })
    
    try:
        logger.info(f"1. GET {pronote_url}")
        res = session.get(pronote_url, allow_redirects=True)
        soup = BeautifulSoup(res.text, 'html.parser')
        form = soup.find('form')
        
        if form:
            action = form.get('action')
            if action.startswith('/'):
                parsed = urlparse(res.url)
                action = f"{parsed.scheme}://{parsed.netloc}{action}"
            
            parsed_url = urlparse(res.url)
            callback = parse_qs(parsed_url.query).get('callback', [''])[0]
            if callback and '?' not in action:
                action += f"?callback={callback}"
            
            user_field = 'email'
            if soup.find('input', {'name': 'username'}): user_field = 'username'
            
            post_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://ent.seine-et-marne.fr',
                'Referer': res.url
            }
            
            logger.info(f"2. POST Identifiants...")
            res_login = session.post(
                action, 
                data={user_field: username, 'password': password},
                headers=post_headers,
                allow_redirects=True
            )
            
            final_res = res_login
            if "ent.seine-et-marne" in res_login.url and callback:
                final_res = session.get(callback, allow_redirects=True)
                
            if "pronote" in final_res.url.lower():
                logger.info("✅ SUCCES : Page Pronote atteinte !")
                return extract_data_from_html(final_res.text, username)
                
        return None

    except Exception as e:
        logger.error(f"Erreur : {e}")
        return None

def extract_data_from_html(html, username):
    soup = BeautifulSoup(html, 'html.parser')
    
    data = {
        'studentData': {'name': username, 'class': 'Classe inconnue', 'average': 0, 'rank': 1, 'totalStudents': 30},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'subjectAverages': [],
        'auth_success': True
    }
    
    try:
        # 1. NOM et CLASSE
        title_match = re.search(r"<title>PRONOTE\s*-\s*([^-\n<]+)", html, re.I)
        if title_match:
            full_name = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()
            if full_name: data['studentData']['name'] = full_name

        script_match = re.search(r"Nom\s*:\s*['\"]([^'\"]+)['\"]", html)
        if script_match: data['studentData']['name'] = script_match.group(1)

        # 2. EMPLOI DU TEMPS (NOUVEAU !)
        # On cherche les éléments <li> avec la classe flex-contain
        # <span class="sr-only">de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE</span>
        
        logger.info("Analyse de l'emploi du temps...")
        
        cours_items = soup.find_all('li', class_='flex-contain')
        
        # Jour actuel (0=Lundi, 6=Dimanche)
        today_idx = datetime.now().weekday()
        if today_idx > 4: today_idx = 0 # Si weekend, montrer lundi
        
        for li in cours_items:
            # Chercher l'heure et la matière
            span_time = li.find('span', class_='sr-only')
            if span_time:
                text = span_time.get_text().strip()
                # Format: "de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE"
                match = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
                
                if match:
                    start_time = match.group(1)
                    end_time = match.group(2)
                    subject = match.group(3).strip()
                    
                    # Chercher prof et salle dans les autres <li> fils
                    details = li.find_all('li')
                    prof = details[0].get_text().strip() if len(details) > 0 else ""
                    room = details[1].get_text().strip() if len(details) > 1 else ""
                    
                    # Couleur par défaut
                    color = 'bg-indigo-500'
                    if 'hist' in subject.lower(): color = 'bg-amber-500'
                    elif 'math' in subject.lower(): color = 'bg-blue-600'
                    elif 'fran' in subject.lower(): color = 'bg-pink-500'
                    elif 'angl' in subject.lower(): color = 'bg-emerald-500'
                    
                    # Ajouter au jour actuel
                    data['schedule'][today_idx].append({
                        'time': f"{start_time} - {end_time}",
                        'subject': subject,
                        'teacher': prof,
                        'room': room,
                        'color': color
                    })
                    
        logger.info(f"Cours trouvés pour aujourd'hui: {len(data['schedule'][today_idx])}")

        # 3. Message de succès
        data['messages'].append({
            'id': 1,
            'from': 'Système',
            'subject': 'Connexion Réussie',
            'date': 'Maintenant',
            'unread': True,
            'content': f"Authentification réussie ! Emploi du temps récupéré."
        })

        return data
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
        return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        req = request.json
        url = req.get('schoolUrl', '')
        if not url.endswith('/'): url += '/'
        
        result = sync_pronote_clone(req.get('username'), req.get('password'), url + 'eleve.html')
        
        if result:
            return jsonify(result)
        return jsonify({'error': 'Échec de connexion'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
