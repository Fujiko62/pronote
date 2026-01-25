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

def sync_pronote_creuzets(username, password, school_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
    })
    
    try:
        # 1. On part de Pronote
        url_initiale = f"{school_url}eleve.html"
        logger.info(f"1. Départ : {url_initiale}")
        res = session.get(url_initiale, allow_redirects=True)
        
        # 2. On mémorise l'URL de retour (callback) demandée par l'ENT
        parsed_url = urlparse(res.url)
        callback = parse_qs(parsed_url.query).get('callback', [None])[0]
        if callback: callback = unquote(callback)
        logger.info(f"   Callback détecté : {callback}")

        # 3. Authentification sur le portail ENT77
        logger.info("2. Authentification ENT...")
        payload = {'email': username, 'password': password}
        # On poste directement sur le login
        auth_res = session.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True)
        
        # 4. ÉTAPE CLÉ : On force la redirection vers Pronote
        # On utilise le callback qu'on a trouvé au début
        logger.info("3. Rebond vers Pronote...")
        final_url = callback if callback else url_initiale
        res_final = session.get(final_url, allow_redirects=True)
        
        # 5. Si on est sur une page de transition (la page de 1316 octets)
        # On cherche si elle contient un lien ou une redirection JS
        if len(res_final.text) < 3000:
            logger.info("   Page de transition détectée, recherche de l'URL finale...")
            # On cherche un identifiant dans le texte
            id_match = re.search(r"identifiant=([a-zA-Z0-9]+)", res_final.text)
            if id_match:
                identifiant = id_match.group(1)
                final_jump = f"{school_url}eleve.html?identifiant={identifiant}"
                logger.info(f"   Saut final vers : {final_jump}")
                res_final = session.get(final_jump, allow_redirects=True)

        logger.info(f"4. Arrivée : {res_final.url} (Taille: {len(res_final.text)})")

        return parse_data_from_html(res_final.text, username)
            
    except Exception as e:
        logger.error(f"Erreur synchro : {e}")
        return None

def parse_data_from_html(html, username):
    data = {
        'studentData': {
            'name': username.replace('.', ' ').title(), 
            'class': '3ème B', # Valeur par défaut
            'average': 0, 'rank': 1, 'totalStudents': 30
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True
    }
    
    try:
        # Extraction du NOM réel
        title_match = re.search(r"PRONOTE\s*-\s*([^/|-]+)", html)
        if title_match:
            data['studentData']['name'] = title_match.group(1).strip()

        # Extraction de l'EMPLOI DU TEMPS (le format sr-only que vous avez trouvé)
        soup = BeautifulSoup(html, 'html.parser')
        cours_items = soup.find_all('li', class_=re.compile(r'flex-contain'))
        
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 # Lundi si weekend
        
        for li in cours_items:
            # On cherche la balise avec l'heure
            span = li.find('span', class_='sr-only')
            if span:
                text = span.get_text()
                # de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE
                m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
                if m:
                    subj = m.group(3).strip()
                    # On cherche le prof et la salle dans les li enfants
                    infos = [i.get_text().strip() for i in li.find_all('li') if i.get_text().strip() != subj]
                    prof = infos[0] if len(infos) > 0 else "Professeur"
                    salle = infos[1] if len(infos) > 1 else "Salle"
                    
                    data['schedule'][day_idx].append({
                        'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                        'subject': subj,
                        'teacher': prof,
                        'room': salle,
                        'color': 'bg-indigo-500'
                    })

        # Message de confirmation
        data['messages'].append({
            'id': 1, 'from': 'Système', 'subject': 'Données synchronisées', 
            'date': 'Maintenant', 'unread': True,
            'content': f"Félicitations ! Votre profil a été mis à jour.\nCours détectés : {len(data['schedule'][day_idx])}"
        })
        
        return data
    except Exception as e:
        logger.error(f"Erreur parsing : {e}")
        return data

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        req = request.json
        url = req.get('schoolUrl', '')
        if not url.endswith('/'): url += '/'
        result = sync_with_ent77_creuzets(req.get('username'), req.get('password'), url)
        if result: return jsonify(result)
        return jsonify({'error': 'Authentification réussie mais impossible de lire les données.'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def sync_with_ent77_creuzets(u, p, s):
    return sync_pronote_clone(u, p, s)

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
