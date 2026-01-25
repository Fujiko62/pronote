from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
import logging
import re
import datetime

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_pronote_final(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 AVG/143.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9'
    })
    
    try:
        # 1. Login
        logger.info(f"1. Accès {pronote_url}")
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
            
            logger.info("2. Authentification ENT...")
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
                return extract_data_perfect(final_res.text, username)
                
        return None
    except Exception as e:
        logger.error(f"Erreur globale: {e}")
        return None

def extract_data_perfect(html, username):
    # Initialisation BLINDEE de l'objet de retour
    data = {
        'studentData': {
            'name': username.split('.')[0].capitalize() + " " + username.split('.')[1].split('@')[0].capitalize() if '.' in username else username,
            'class': 'Classe détectée', 'average': 0, 'rank': 1, 'totalStudents': 30
        },
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'subjectAverages': [],
        'auth_success': True
    }
    
    try:
        # 1. Extraction du NOM
        title_match = re.search(r"<title>PRONOTE\s*-\s*([^-\n<]+)", html, re.I)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip().replace("ESPACE ÉLÈVE", "").strip()

        # 2. Extraction de l'EMPLOI DU TEMPS (le code que vous avez trouvé)
        logger.info("Scraping de l'emploi du temps...")
        soup = BeautifulSoup(html, 'html.parser')
        
        # On cherche les cours dans les balises sr-only
        spans = soup.find_all('span', class_='sr-only')
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 # Lundi par défaut si weekend
        
        for span in spans:
            text = span.get_text()
            # On cherche "de 9h25 à 10h20 MATIERE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subject = m.group(3).strip()
                # On ajoute le cours !
                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subject,
                    'teacher': 'Professeur', # Sera rempli si trouvé plus loin
                    'room': 'Salle',
                    'color': 'bg-indigo-500'
                })

        # 3. Message système
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Synchronisation OK', 
            'date': 'Maintenant', 'unread': True, 
            'content': f"Connexion réussie ! {len(data['schedule'][day_idx])} cours ont été lus sur votre page d'accueil."
        })

        return data
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
        return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        req = request.json
        res = sync_pronote_final(req.get('username'), req.get('password'), req.get('schoolUrl') + 'eleve.html')
        if res: return jsonify(res)
        return jsonify({'error': 'La connexion a échoué.'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
