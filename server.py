import os
import re
import json
import logging
import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import urlparse, parse_qs, unquote, urljoin

app = Flask(__name__)
CORS(app)

# Configuration des logs détaillés
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION HARDCODÉE POUR TON ÉCOLE
# ============================================
CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message, data=None):
    """Log formaté pour chaque étape"""
    emoji = {
        'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 
        'success': '✅', 'error': '❌', 'info': 'ℹ️', 'form': '📝',
        'cookie': '🍪', 'debug': '🐛'
    }
    icon = emoji.get(step, '📌')
    logger.info(f"{icon} [{step.upper()}] {message}")
    if data:
        logger.info(f"   └── {data}")

def extract_data_from_pronote(html, username, url_reached):
    """Extraction des données depuis la page Pronote"""
    display_name = username.split('@')[0].replace('.', ' ').title()
    
    data = {
        'studentData': {
            'name': display_name, 
            'class': 'Non détectée', 
            'average': None,
            'rank': None
        },
        'schedule': [[], [], [], [], []],  # Lundi à Vendredi
        'homework': [],
        'grades': [],
        'messages': [],
        'subjectAverages': [],
        'auth_success': True,
        'raw_found': [f"URL atteinte: {url_reached}", f"Taille page: {len(html)} bytes"]
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extraction du nom depuis le titre
        title = soup.title.string if soup.title else ""
        log_step('extract', f"Titre de la page: {title[:60]}...")
        
        if title and "-" in title:
            parts = title.split('-')
            for part in parts:
                clean = part.strip().replace("ESPACE ÉLÈVE", "").replace("PRONOTE", "").strip()
                if clean and len(clean) > 2 and clean.upper() != clean:
                    data['studentData']['name'] = clean
                    log_step('success', f"Nom trouvé: {clean}")
                    break
        
        # 2. Extraction de la classe
        class_patterns = [
            r'(\d+)(?:ème|EME|e|è)\s*([A-Z0-9])?',
            r'(3|4|5|6)(?:EME|ème|e)\s*([A-Z])?',
            r'classe[:\s]+(\d+[eè](?:me)?\s*[A-Z]?)',
        ]
        for pattern in class_patterns:
            match = re.search(pattern, html, re.I)
            if match:
                classe = match.group(0).strip().upper()
                data['studentData']['class'] = classe
                log_step('success', f"Classe trouvée: {classe}")
                break
        
        # 3. Extraction de l'emploi du temps (balises sr-only)
        day_idx = datetime.datetime.now().weekday()
        if day_idx > 4:
            day_idx = 0
        
        log_step('extract', f"Recherche emploi du temps (jour index: {day_idx})...")
        
        # Chercher toutes les balises sr-only
        sr_only_spans = soup.find_all('span', class_='sr-only')
        sr_only_count = len(sr_only_spans)
        log_step('info', f"Balises sr-only trouvées: {sr_only_count}")
        
        for span in sr_only_spans:
            text = span.get_text(" ", strip=True)
            
            # Pattern: "de 8h30 à 9h25 MATHEMATIQUES"
            match = re.search(r"de\s+(\d{1,2}h\d{2})\s+à\s+(\d{1,2}h\d{2})\s+(.+)", text, re.I)
            if match:
                start_time = match.group(1)
                end_time = match.group(2)
                subject = match.group(3).strip()
                
                # Ignorer les pauses
                if any(x in subject.lower() for x in ['pause', 'récréation', 'déjeuner', 'repas']):
                    continue
                
                # Chercher prof et salle dans les éléments proches
                teacher = ""
                room = ""
                parent = span.find_parent(['li', 'div', 'td'])
                if parent:
                    all_text = parent.get_text(" ", strip=True)
                    # Chercher une salle (ex: "Salle A204", "S.204", etc.)
                    room_match = re.search(r'(?:salle|S\.?)\s*([A-Z]?\d{2,3}[A-Z]?)', all_text, re.I)
                    if room_match:
                        room = room_match.group(1)
                
                course = {
                    'time': f"{start_time.replace('h', ':')} - {end_time.replace('h', ':')}",
                    'subject': subject,
                    'teacher': teacher,
                    'room': room or 'Salle',
                    'color': 'bg-indigo-500'
                }
                data['schedule'][day_idx].append(course)
                data['raw_found'].append(f"Cours: {subject} ({start_time}-{end_time})")
                log_step('success', f"Cours trouvé: {subject}")
        
        log_step('info', f"Total cours aujourd'hui: {len(data['schedule'][day_idx])}")
        
        # 4. Chercher les devoirs
        devoir_keywords = ['devoir', 'travail', 'exercice', 'pour le', 'à faire', 'à rendre']
        text_blocks = soup.find_all(['div', 'li', 'p', 'span'])
        
        for block in text_blocks:
            text = block.get_text(" ", strip=True).lower()
            if any(kw in text for kw in devoir_keywords) and len(text) > 20:
                # Vérifier que ce n'est pas un doublon
                if text[:50] not in [h['description'][:50].lower() for h in data['homework']]:
                    data['homework'].append({
                        'id': len(data['homework']) + 1,
                        'subject': 'À déterminer',
                        'title': block.get_text(" ", strip=True)[:100],
                        'dueDate': (datetime.datetime.now() + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
                        'done': False,
                        'description': block.get_text(" ", strip=True)
                    })
                    if len(data['homework']) >= 10:
                        break
        
        log_step('info', f"Devoirs trouvés: {len(data['homework'])}")
        
        # 5. Chercher les notes
        note_pattern = re.compile(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*/\s*(\d{1,2})')
        for block in text_blocks:
            text = block.get_text(" ", strip=True)
            matches = note_pattern.findall(text)
            for match in matches:
                try:
                    grade = float(match[0].replace(',', '.'))
                    out_of = int(match[1])
                    if 0 <= grade <= out_of <= 20:
                        data['grades'].append({
                            'subject': 'Matière',
                            'grade': grade,
                            'outOf': out_of,
                            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                            'title': text[:50],
                            'average': None,
                            'coef': 1
                        })
                except:
                    pass
        
        log_step('info', f"Notes trouvées: {len(data['grades'])}")
        
    except Exception as e:
        log_step('error', f"Erreur extraction: {str(e)}")
        data['raw_found'].append(f"Erreur: {str(e)}")
    
    return data

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        username = req.get('username', '')
        password = req.get('password', '')
        
        log_step('start', "=" * 60)
        log_step('start', "NOUVELLE SYNCHRONISATION - Collège Les Creuzets")
        log_step('start', "=" * 60)
        log_step('info', f"Utilisateur: {username.split('@')[0] if '@' in username else username[:15]}***")
        log_step('info', f"URL Pronote: {CONFIG['SCHOOL_URL']}")
        
        if not username or not password:
            log_step('error', "Identifiants manquants!")
            return jsonify({'error': 'Identifiants requis', 'auth_success': False}), 400
        
        # Créer une session avec des headers réalistes
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # ==========================================
        # ÉTAPE 1: Accéder à Pronote (sera redirigé vers ENT)
        # ==========================================
        log_step('auth', f"Accès à Pronote: {CONFIG['SCHOOL_URL']}eleve.html")
        
        try:
            response = session.get(
                f"{CONFIG['SCHOOL_URL']}eleve.html",
                allow_redirects=True,
                timeout=30
            )
            log_step('redirect', f"Redirigé vers: {response.url[:80]}...")
            log_step('info', f"Status: {response.status_code}, Taille: {len(response.text)} bytes")
        except Exception as e:
            log_step('error', f"Erreur accès Pronote: {str(e)}")
            return jsonify({'error': f'Impossible d\'accéder à Pronote: {str(e)}', 'auth_success': False}), 500
        
        current_url = response.url
        
        # ==========================================
        # ÉTAPE 2: Détecter et extraire le callback
        # ==========================================
        parsed = urlparse(current_url)
        query_params = parse_qs(parsed.query)
        callback = query_params.get('callback', [None])[0]
        
        if callback:
            callback = unquote(callback)
            log_step('success', f"Callback trouvé dans URL!")
            log_step('debug', f"Callback: {callback[:80]}...")
        else:
            # Chercher dans le HTML
            callback_match = re.search(r'callback=([^&"\'>\s]+)', response.text)
            if callback_match:
                callback = unquote(callback_match.group(1))
                log_step('success', f"Callback trouvé dans HTML!")
        
        if not callback:
            log_step('error', "Aucun callback trouvé")
            return jsonify({
                'error': 'Callback de sécurité introuvable',
                'auth_success': False,
                'debug_url': current_url
            }), 401
        
        # ==========================================
        # ÉTAPE 3: Analyser la page de login ENT
        # ==========================================
        log_step('form', "Analyse de la page de login ENT...")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Trouver le formulaire de login
        login_form = soup.find('form')
        if not login_form:
            log_step('error', "Formulaire de login non trouvé!")
            return jsonify({'error': 'Page de login non trouvée', 'auth_success': False}), 401
        
        # Déterminer l'URL d'action du formulaire
        form_action = login_form.get('action', '')
        if form_action:
            if not form_action.startswith('http'):
                form_action = urljoin(current_url, form_action)
            log_step('info', f"Form action: {form_action[:60]}...")
        else:
            form_action = current_url
            log_step('info', "Form action: URL courante")
        
        # Collecter tous les champs du formulaire
        form_data = {}
        
        # Champs cachés
        hidden_inputs = login_form.find_all('input', type='hidden')
        for inp in hidden_inputs:
            name = inp.get('name')
            value = inp.get('value', '')
            if name:
                form_data[name] = value
                log_step('debug', f"Champ caché: {name}={value[:30] if value else '(vide)'}...")
        
        # Trouver les champs email/username
        email_field = None
        for name in ['email', 'username', 'login', 'user', 'identifiant', 'mail']:
            field = login_form.find('input', {'name': name})
            if field:
                email_field = name
                break
        
        if not email_field:
            # Chercher par type
            field = login_form.find('input', {'type': 'email'})
            if field and field.get('name'):
                email_field = field.get('name')
            else:
                field = login_form.find('input', {'type': 'text'})
                if field and field.get('name'):
                    email_field = field.get('name')
        
        if not email_field:
            email_field = 'email'  # Défaut
        
        log_step('info', f"Champ identifiant: {email_field}")
        
        # Trouver le champ password
        password_field = None
        pwd_input = login_form.find('input', {'type': 'password'})
        if pwd_input and pwd_input.get('name'):
            password_field = pwd_input.get('name')
        else:
            password_field = 'password'
        
        log_step('info', f"Champ mot de passe: {password_field}")
        
        # Ajouter les identifiants
        form_data[email_field] = username
        form_data[password_field] = password
        
        log_step('info', f"Nombre de champs: {len(form_data)}")
        
        # ==========================================
        # ÉTAPE 4: Soumettre le formulaire de login
        # ==========================================
        log_step('auth', f"Envoi des identifiants à: {form_action[:50]}...")
        
        try:
            login_response = session.post(
                form_action,
                data=form_data,
                allow_redirects=True,
                timeout=30
            )
            log_step('info', f"Réponse login: {login_response.status_code}")
            log_step('redirect', f"URL après login: {login_response.url[:60]}...")
        except Exception as e:
            log_step('error', f"Erreur lors du login: {str(e)}")
            return jsonify({'error': f'Erreur login: {str(e)}', 'auth_success': False}), 500
        
        # Vérifier si on est toujours sur la page de login (échec)
        if 'login' in login_response.url.lower() and 'auth' in login_response.url.lower():
            # Chercher un message d'erreur
            error_soup = BeautifulSoup(login_response.text, 'html.parser')
            error_msg = error_soup.find(class_=re.compile(r'error|alert|message', re.I))
            error_text = error_msg.get_text(strip=True) if error_msg else "Identifiants incorrects"
            
            log_step('error', f"Échec login: {error_text[:50]}...")
            return jsonify({
                'error': f'Échec authentification: {error_text[:100]}',
                'auth_success': False
            }), 401
        
        log_step('success', "Login ENT réussi!")
        
        # ==========================================
        # ÉTAPE 5: Suivre le callback vers Pronote
        # ==========================================
        log_step('redirect', "Retour vers Pronote...")
        
        # Vérifier si on est déjà sur Pronote
        if 'pronote' in login_response.url.lower() or 'index-education' in login_response.url.lower():
            final_response = login_response
            log_step('success', "Déjà sur Pronote!")
        else:
            # Suivre le callback
            try:
                final_response = session.get(callback, allow_redirects=True, timeout=30)
                log_step('info', f"URL finale: {final_response.url[:60]}...")
            except Exception as e:
                log_step('error', f"Erreur callback: {str(e)}")
                return jsonify({'error': f'Erreur retour Pronote: {str(e)}', 'auth_success': False}), 500
        
        # Si toujours pas sur Pronote, essayer directement
        if 'pronote' not in final_response.url.lower() and 'index-education' not in final_response.url.lower():
            log_step('info', "Tentative accès direct à Pronote...")
            try:
                final_response = session.get(
                    f"{CONFIG['SCHOOL_URL']}eleve.html",
                    allow_redirects=True,
                    timeout=30
                )
            except:
                pass
        
        # ==========================================
        # ÉTAPE 6: Vérifier qu'on est sur Pronote
        # ==========================================
        final_url = final_response.url
        log_step('info', f"URL finale: {final_url}")
        
        is_on_pronote = 'pronote' in final_url.lower() or 'index-education' in final_url.lower()
        
        if not is_on_pronote:
            log_step('error', f"Non redirigé vers Pronote. URL: {final_url[:80]}")
            return jsonify({
                'error': 'Impossible d\'accéder à Pronote après login',
                'auth_success': False,
                'final_url': final_url
            }), 401
        
        log_step('success', "Page Pronote atteinte!")
        
        # ==========================================
        # ÉTAPE 7: Extraire les données
        # ==========================================
        log_step('extract', "Extraction des données...")
        
        result = extract_data_from_pronote(final_response.text, username, final_url)
        
        # Log du résumé
        log_step('success', "=" * 60)
        log_step('success', "SYNCHRONISATION TERMINÉE")
        log_step('success', "=" * 60)
        log_step('info', f"Élève: {result['studentData']['name']}")
        log_step('info', f"Classe: {result['studentData']['class']}")
        log_step('info', f"Cours aujourd'hui: {sum(len(day) for day in result['schedule'])}")
        log_step('info', f"Devoirs: {len(result['homework'])}")
        log_step('info', f"Notes: {len(result['grades'])}")
        
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
        'version': '2.1',
        'school': CONFIG['SCHOOL_NAME']
    })


@app.route('/')
def home():
    return jsonify({
        'name': 'Pronote Bridge Server',
        'version': '2.1',
        'school': CONFIG['SCHOOL_NAME'],
        'endpoints': {
            '/': 'GET - Cette page',
            '/health': 'GET - Health check',
            '/sync': 'POST - Synchronisation (username, password)'
        },
        'status': 'running 🚀'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Démarrage serveur Pronote Bridge sur port {port}")
    app.run(host='0.0.0.0', port=port)
