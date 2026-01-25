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
        'Accept-Language': 'fr-FR,fr;q=0.9'
    })
    
    try:
        # 1. Login
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
                
                # 2. APPEL API JSON POUR AVOIR L'EDT
                # Pronote charge l'EDT via un appel POST specifique
                # On va essayer de scraper la page actuelle d'abord
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

        # 2. EMPLOI DU TEMPS (NOUVEAU !)
        # Recherche des elements caches dans le HTML brut
        # <span class="sr-only">de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE</span>
        
        logger.info("Analyse de l'emploi du temps...")
        
        # On cherche tous les spans sr-only qui contiennent "de ... à ..."
        spans = soup.find_all('span', class_='sr-only')
        
        # On determine le jour actuel (lundi=0)
        # Pronote affiche souvent l'EDT du jour ou de la semaine
        # Pour simplifier, on met tout dans le jour 0 (Lundi) ou le jour actuel
        today_idx = datetime.datetime.now().weekday()
        if today_idx > 4: today_idx = 0
        
        count = 0
        for span in spans:
            text = span.get_text().strip()
            # Regex: de HHhMM à HHhMM MATIERE
            match = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            
            if match:
                start = match.group(1).replace('h', ':')
                end = match.group(2).replace('h', ':')
                subject = match.group(3).strip()
                
                # Chercher le prof et la salle
                # Ils sont souvent dans des <li> juste apres le span
                prof = ""
                room = ""
                
                parent = span.find_parent('li')
                if parent:
                    # Chercher les autres li dans le meme conteneur
                    siblings = parent.find_all('li')
                    for sib in siblings:
                        sib_text = sib.get_text().strip()
                        if sib_text and sib_text != subject:
                            if not prof: prof = sib_text
                            elif not room: room = sib_text
                
                # Couleur
                color = 'bg-indigo-500'
                subj_lower = subject.lower()
                if 'hist' in subj_lower: color = 'bg-amber-500'
                elif 'math' in subj_lower: color = 'bg-blue-600'
                elif 'fran' in subj_lower: color = 'bg-pink-500'
                elif 'angl' in subj_lower: color = 'bg-emerald-500'
                elif 'phys' in subj_lower: color = 'bg-purple-600'
                elif 'svt' in subj_lower: color = 'bg-green-600'
                
                data['schedule'][today_idx].append({
                    'time': f"{start} - {end}",
                    'subject': subject,
                    'teacher': prof,
                    'room': room,
                    'color': color
                })
                count += 1
                
        logger.info(f"✅ {count} cours trouves !")
        
        # Si on a trouve des cours, on met a jour le message
        if count > 0:
            msg = f"Authentification réussie ! {count} cours récupérés pour aujourd'hui."
        else:
            msg = "Authentification réussie ! (Aucun cours détecté dans le HTML)"
            
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Connexion Réussie', 
            'date': 'Maintenant', 'unread': True, 'content': msg
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
