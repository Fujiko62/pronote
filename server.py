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

# Configuration des logs détaillés
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)

def log_step(step, message, data=None):
    """Log formaté pour chaque étape"""
    emoji = {'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 'success': '✅', 'error': '❌', 'info': 'ℹ️'}
    icon = emoji.get(step, '📌')
    logger.info(f"{icon} [{step.upper()}] {message}")
    if data:
        logger.info(f"   └── {data}")

def extract_surgical_data(html, username, url_reached):
    """Extraction ultra-précise des données de l'école Les Creuzets"""
    # Nom par défaut basé sur l'identifiant
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {
            'name': display_name, 
            'class': 'Non détectée', 
            'average': 15.2, # Valeur démo
            'rank': 1
        },
        'schedule': [[], [], [], [], []],
        'homework': [], 'grades': [], 'messages': [], 'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL atteinte : {url_reached}", f"Taille page : {len(html)}"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du VRAI NOM (depuis le titre de la page Pronote)
        title = soup.title.string if soup.title else ""
        if "PRONOTE" in title and "-" in title:
            extracted_name = title.split('-')[1].strip().replace("ESPACE ÉLÈVE", "").strip()
            if extracted_name: data['studentData']['name'] = extracted_name

        # 2. Extraction de la CLASSE (Cherche 6EME, 5EME, 4EME, 3EME)
        class_m = re.search(r"(\d+(?:EME|eme|ème|e|è)\s*[A-Z0-9]?)", html)
        if class_m:
            data['studentData']['class'] = class_m.group(1).upper()

        # 3. Extraction de l'EMPLOI DU TEMPS (Ton format spécifique)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4: day_idx = 0 # Si weekend, affiche lundi
        
        spans = soup.find_all('span', class_='sr-only')
        for span in spans:
            text = span.get_text(" ").strip()
            # Regex magique pour : "de 9h25 à 10h20 HISTOIRE-GEOGRAPHIE"
            m = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
            if m:
                subj = m.group(3).strip()
                if "pause" in subj.lower(): continue # Ignore la récré/déjeuner

                # Chercher le prof et la salle dans le même bloc
                p_li = span.find_parent('li')
                prof, room = "Non spécifié", "Salle"
                if p_li:
                    details = [d.get_text().strip() for d in p_li.find_all('li') if d.get_text().strip() and d.get_text().strip() != subj]
                    if len(details) >= 1: prof = details[0]
                    if len(details) >= 2: room = details[1]

                data['schedule'][day_idx].append({
                    'time': f"{m.group(1).replace('h', ':')} - {m.group(2).replace('h', ':')}",
                    'subject': subj, 'teacher': prof, 'room': room, 'color': 'bg-indigo-500'
                })
                data['raw_found'].append(f"Cours trouvé : {subj}")

    except Exception as e:
        data['raw_found'].append(f"Erreur d'extraction : {str(e)}")
        
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        u = req.get('username', '')
        p = req.get('password', '')
        school_url = req.get('schoolUrl', '')
        
        log_step('start', f"Nouvelle synchronisation")
        log_step('info', f"Utilisateur: {u.split('@')[0]}***")
        log_step('info', f"URL École: {school_url}")
        
        if not school_url:
            log_step('error', "URL de l'école manquante!")
            return jsonify({'error': 'URL de l\'école requise', 'auth_success': False}), 400
            
        if not school_url.endswith('/'): school_url += '/'
        
        # Session avec headers réalistes
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        })
        
        # ÉTAPE 1 : Appel Pronote pour obtenir le callback
        log_step('auth', f"Accès à Pronote: {school_url}eleve.html")
        try:
            res_init = s.get(school_url + "eleve.html", allow_redirects=True, timeout=30)
            log_step('redirect', f"Redirigé vers: {res_init.url[:80]}...")
            log_step('info', f"Status: {res_init.status_code}, Taille: {len(res_init.text)} bytes")
        except Exception as e:
            log_step('error', f"Impossible d'accéder à Pronote: {str(e)}")
            return jsonify({'error': f'Impossible d\'accéder à Pronote: {str(e)}', 'auth_success': False}), 500
        
        # Extraction du callback CAS
        parsed_url = urlparse(res_init.url)
        callback = parse_qs(parsed_url.query).get('callback', [None])[0]
        
        log_step('info', f"Callback trouvé: {'OUI ✓' if callback else 'NON ✗'}")
        
        if not callback:
            # Chercher le callback dans le HTML
            callback_match = re.search(r'callback=([^&"\']+)', res_init.text)
            if callback_match:
                callback = unquote(callback_match.group(1))
                log_step('info', f"Callback extrait du HTML: OUI ✓")
        
        if not callback:
            log_step('error', "Aucun callback CAS trouvé")
            return jsonify({
                'error': 'Lien de sécurité introuvable. Vérifiez l\'URL de l\'école.',
                'auth_success': False,
                'debug': {
                    'url_finale': res_init.url,
                    'contient_cas': 'cas' in res_init.url.lower(),
                    'contient_ent': 'ent' in res_init.url.lower()
                }
            }), 401

        # ÉTAPE 2 : Connexion ENT Seine-et-Marne
        log_step('auth', "Connexion à l'ENT Seine-et-Marne...")
        
        payload = {'email': u, 'password': p}
        try:
            res_login = s.post("https://ent.seine-et-marne.fr/auth/login", data=payload, allow_redirects=True, timeout=30)
            log_step('auth', f"Réponse ENT: {res_login.status_code}")
            log_step('redirect', f"URL après login: {res_login.url[:60]}...")
            
            if 'auth/login' in res_login.url:
                log_step('error', "Échec authentification ENT (toujours sur login)")
                return jsonify({
                    'error': 'Identifiants ENT incorrects',
                    'auth_success': False
                }), 401
                
        except Exception as e:
            log_step('error', f"Erreur connexion ENT: {str(e)}")
            return jsonify({'error': f'Erreur ENT: {str(e)}', 'auth_success': False}), 500
        
        # ÉTAPE 3 : Suivre le callback vers Pronote
        log_step('redirect', "Retour vers Pronote via callback...")
        try:
            res_final = s.get(unquote(callback), allow_redirects=True, timeout=30)
            log_step('success', f"Page Pronote atteinte: {res_final.url[:60]}...")
            log_step('info', f"Taille page finale: {len(res_final.text)} bytes")
        except Exception as e:
            log_step('error', f"Erreur callback: {str(e)}")
            return jsonify({'error': f'Erreur retour Pronote: {str(e)}', 'auth_success': False}), 500
        
        if "index-education.net" not in res_final.url and "pronote" not in res_final.url.lower():
            log_step('info', "Pas sur Pronote, tentative directe...")
            res_final = s.get(school_url + "eleve.html", allow_redirects=True, timeout=30)
            log_step('info', f"URL finale: {res_final.url[:60]}...")

        # ÉTAPE 4 : Extraction des données
        log_step('extract', "Extraction des données...")
        result = extract_surgical_data(res_final.text, u, res_final.url)
        
        log_step('success', f"Extraction terminée!")
        log_step('info', f"Élève: {result['studentData']['name']}")
        log_step('info', f"Classe: {result['studentData']['class']}")
        log_step('info', f"Cours trouvés: {sum(len(day) for day in result['schedule'])}")
        
        return jsonify(result)

    except Exception as e:
        log_step('error', f"Erreur générale: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e), 'auth_success': False}), 500

@app.route('/health')
def health(): 
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.datetime.now().isoformat(),
        'version': '2.0'
    })

@app.route('/')
def home():
    return jsonify({
        'name': 'Pronote Bridge Server',
        'version': '2.0',
        'endpoints': {
            '/health': 'GET - Health check',
            '/sync': 'POST - Synchronisation Pronote (username, password, schoolUrl)'
        },
        'status': 'running'
    })

@app.route('/debug', methods=['POST'])
def debug_html():
    """Endpoint pour tester l'extraction sur du HTML fourni"""
    req = request.json
    html = req.get('html', '')
    username = req.get('username', 'test@test.fr')
    
    if not html:
        return jsonify({'error': 'HTML requis'}), 400
    
    result = extract_surgical_data(html, username, 'debug-mode')
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Démarrage du serveur Pronote Bridge sur le port {port}")
    app.run(host='0.0.0.0', port=port)
