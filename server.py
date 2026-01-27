import os
import re
import json
import logging
import datetime
import asyncio
from flask import Flask, request, jsonify
from flask_cors import CORS

# Configuration des logs détaillés
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============================================
# CONFIGURATION HARDCODÉE
# ============================================
CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'ENT_URL': 'https://ent.seine-et-marne.fr',
    'ENT77_URL': 'https://ent77.seine-et-marne.fr',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message, data=None):
    """Log formaté pour chaque étape"""
    emoji = {
        'start': '🚀', 'auth': '🔐', 'redirect': '↪️', 'extract': '🔍', 
        'success': '✅', 'error': '❌', 'info': 'ℹ️', 'browser': '🌐',
        'click': '👆', 'type': '⌨️', 'wait': '⏳', 'screenshot': '📸'
    }
    icon = emoji.get(step, '📌')
    logger.info(f"{icon} [{step.upper()}] {message}")
    if data:
        logger.info(f"   └── {data}")

async def scrape_with_playwright(username, password):
    """
    Utilise Playwright pour simuler un vrai utilisateur et extraire les données.
    C'est comme si quelqu'un ouvrait un navigateur et cliquait sur les boutons.
    """
    from playwright.async_api import async_playwright
    
    data = {
        'studentData': {'name': '', 'class': '', 'average': None, 'rank': None},
        'schedule': [[], [], [], [], []],  # Lundi à Vendredi
        'homework': [],
        'grades': [],
        'messages': [],
        'absences': [],
        'teacherAbsences': [],  # Profs absents
        'news': [],  # Actualités
        'subjectAverages': [],
        'auth_success': False,
        'raw_found': [],
        'screenshots': []  # Pour debug
    }
    
    async with async_playwright() as p:
        # Lance un navigateur (headless = sans fenêtre visible)
        log_step('browser', 'Lancement du navigateur Chrome...')
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            locale='fr-FR'
        )
        
        page = await context.new_page()
        
        try:
            # ==========================================
            # ÉTAPE 1: Accès à Pronote (redirige vers ENT)
            # ==========================================
            log_step('browser', f"Navigation vers Pronote: {CONFIG['SCHOOL_URL']}eleve.html")
            await page.goto(f"{CONFIG['SCHOOL_URL']}eleve.html", wait_until='networkidle', timeout=30000)
            
            current_url = page.url
            log_step('redirect', f"URL actuelle: {current_url[:80]}...")
            data['raw_found'].append(f"URL après Pronote: {current_url}")
            
            # ==========================================
            # ÉTAPE 2: Connexion ENT
            # ==========================================
            if 'ent' in current_url.lower() or 'seine-et-marne' in current_url.lower():
                log_step('auth', "Page ENT détectée, recherche du formulaire de login...")
                
                await page.wait_for_load_state('networkidle')
                
                # Chercher les champs de connexion
                email_selectors = [
                    'input[name="email"]',
                    'input[name="username"]', 
                    'input[name="login"]',
                    'input[type="email"]',
                    'input[id="email"]',
                    'input[id="username"]',
                    '#email',
                    '#username',
                    'input[placeholder*="dentifiant"]',
                    'input[placeholder*="mail"]'
                ]
                
                password_selectors = [
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[id="password"]',
                    '#password'
                ]
                
                # Trouver le champ email
                email_field = None
                for selector in email_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            email_field = selector
                            log_step('info', f"Champ email trouvé: {selector}")
                            break
                    except:
                        continue
                
                # Trouver le champ password
                password_field = None
                for selector in password_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            password_field = selector
                            log_step('info', f"Champ password trouvé: {selector}")
                            break
                    except:
                        continue
                
                if email_field and password_field:
                    log_step('type', f"Saisie de l'identifiant: {username.split('@')[0]}***")
                    await page.fill(email_field, username)
                    
                    log_step('type', "Saisie du mot de passe: ********")
                    await page.fill(password_field, password)
                    
                    # Chercher et cliquer sur le bouton de connexion
                    submit_selectors = [
                        'button[type="submit"]',
                        'input[type="submit"]',
                        'button:has-text("Connexion")',
                        'button:has-text("Se connecter")',
                        'button:has-text("Valider")',
                        '.btn-primary',
                        '#submit',
                        'button.submit'
                    ]
                    
                    for selector in submit_selectors:
                        try:
                            if await page.locator(selector).count() > 0:
                                log_step('click', f"Clic sur: {selector}")
                                await page.click(selector)
                                break
                        except:
                            continue
                    
                    log_step('wait', "Attente de la redirection après login...")
                    await page.wait_for_load_state('networkidle', timeout=15000)
                    await asyncio.sleep(2)
                    
                    current_url = page.url
                    log_step('redirect', f"URL après login: {current_url[:80]}...")
                    data['raw_found'].append(f"URL après login: {current_url}")
                    
                    if 'login' in current_url.lower() or 'auth' in current_url.lower():
                        error_msg = await page.locator('.error, .alert-danger, .message-error').text_content() if await page.locator('.error, .alert-danger, .message-error').count() > 0 else None
                        log_step('error', f"Échec de connexion: {error_msg or 'Identifiants incorrects'}")
                        data['raw_found'].append(f"Erreur login: {error_msg or 'Échec authentification'}")
                        await browser.close()
                        return data
                    
                    data['auth_success'] = True
                    log_step('success', "Connexion ENT réussie!")
                else:
                    log_step('error', "Champs de login non trouvés sur la page ENT")
                    data['raw_found'].append("Champs login non trouvés")
            
            # ==========================================
            # ÉTAPE 3: Navigation vers Pronote
            # ==========================================
            if 'pronote' not in page.url.lower() and 'index-education' not in page.url.lower():
                log_step('browser', "Recherche du lien Pronote sur le portail ENT...")
                
                pronote_selectors = [
                    'a:has-text("Pronote")',
                    'a:has-text("PRONOTE")',
                    'a[href*="pronote"]',
                    'a[href*="index-education"]',
                    '.app-pronote',
                    '[data-app="pronote"]'
                ]
                
                for selector in pronote_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            log_step('click', f"Clic sur Pronote: {selector}")
                            await page.click(selector)
                            await page.wait_for_load_state('networkidle', timeout=15000)
                            break
                    except:
                        continue
                
                current_url = page.url
                log_step('redirect', f"URL après clic Pronote: {current_url[:80]}...")
            
            # ==========================================
            # ÉTAPE 4: Extraction des données Pronote
            # ==========================================
            if 'pronote' in page.url.lower() or 'index-education' in page.url.lower():
                log_step('success', "Page Pronote atteinte!")
                log_step('extract', "Début de l'extraction des données...")
                
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(2)
                
                # --- Extraction du nom de l'élève ---
                name_selectors = [
                    '.NOM_UTILISATEUR',
                    '.nom-utilisateur',
                    '[class*="nom"]',
                    '.user-name',
                    '#NOM'
                ]
                for selector in name_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            name = await page.locator(selector).first.text_content()
                            if name and len(name.strip()) > 2:
                                data['studentData']['name'] = name.strip()
                                log_step('info', f"Nom trouvé: {name.strip()}")
                                break
                    except:
                        continue
                
                # Si pas trouvé, essayer le titre de la page
                if not data['studentData']['name']:
                    title = await page.title()
                    if title and '-' in title:
                        name = title.split('-')[1].strip() if len(title.split('-')) > 1 else ''
                        name = name.replace('ESPACE ÉLÈVE', '').strip()
                        if name:
                            data['studentData']['name'] = name
                            log_step('info', f"Nom depuis titre: {name}")
                
                # --- Extraction de la classe ---
                page_content = await page.content()
                class_match = re.search(r'(\d+(?:ème|EME|e|è)[A-Z0-9\s]*)', page_content, re.I)
                if class_match:
                    data['studentData']['class'] = class_match.group(1).strip().upper()
                    log_step('info', f"Classe trouvée: {data['studentData']['class']}")
                
                # --- Extraction emploi du temps (sr-only) ---
                log_step('extract', "Extraction de l'emploi du temps...")
                sr_only_elements = await page.locator('.sr-only, [class*="sr-only"]').all()
                day_idx = datetime.datetime.now().weekday()
                if day_idx > 4: day_idx = 0
                
                for el in sr_only_elements:
                    try:
                        text = await el.text_content()
                        if text:
                            match = re.search(r"de\s+(\d+h\d+)\s+à\s+(\d+h\d+)\s+(.+)", text, re.I)
                            if match:
                                subject = match.group(3).strip()
                                if 'pause' not in subject.lower():
                                    course = {
                                        'time': f"{match.group(1).replace('h', ':')} - {match.group(2).replace('h', ':')}",
                                        'subject': subject,
                                        'teacher': '',
                                        'room': '',
                                        'color': 'bg-indigo-500'
                                    }
                                    data['schedule'][day_idx].append(course)
                                    data['raw_found'].append(f"Cours: {subject}")
                    except:
                        continue
                
                log_step('info', f"Cours trouvés aujourd'hui: {len(data['schedule'][day_idx])}")
                
                # --- Extraction des devoirs ---
                log_step('extract', "Extraction des devoirs...")
                homework_elements = await page.locator('[class*="devoir"], [class*="travail"], .homework, [data-type="homework"]').all()
                for i, el in enumerate(homework_elements[:10]):
                    try:
                        text = await el.text_content()
                        if text and len(text) > 5:
                            data['homework'].append({
                                'id': i + 1,
                                'subject': 'À déterminer',
                                'title': text.strip()[:100],
                                'dueDate': datetime.datetime.now().strftime('%Y-%m-%d'),
                                'done': False,
                                'description': text.strip()
                            })
                            data['raw_found'].append(f"Devoir: {text[:50]}...")
                    except:
                        continue
                
                log_step('info', f"Devoirs trouvés: {len(data['homework'])}")
                
                # --- Extraction des notes ---
                log_step('extract', "Extraction des notes...")
                grade_pattern = re.compile(r'(\d{1,2}(?:[.,]\d+)?)\s*/\s*(\d{1,2})')
                grade_elements = await page.locator('[class*="note"], [class*="grade"], .note, .moyenne').all()
                for el in grade_elements[:20]:
                    try:
                        text = await el.text_content()
                        if text:
                            match = grade_pattern.search(text)
                            if match:
                                grade_val = float(match.group(1).replace(',', '.'))
                                out_of = int(match.group(2))
                                if 0 <= grade_val <= out_of <= 20:
                                    data['grades'].append({
                                        'subject': 'Matière',
                                        'grade': grade_val,
                                        'outOf': out_of,
                                        'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                                        'title': text.strip()[:50],
                                        'average': None,
                                        'coef': 1
                                    })
                                    data['raw_found'].append(f"Note: {grade_val}/{out_of}")
                    except:
                        continue
                
                log_step('info', f"Notes trouvées: {len(data['grades'])}")
                
                # --- Extraction des absences de profs ---
                log_step('extract', "Recherche des profs absents...")
                absence_selectors = [
                    '[class*="absence"]',
                    '[class*="absent"]',
                    '[class*="annul"]',
                    '.cours-annule',
                    '[style*="line-through"]'
                ]
                for selector in absence_selectors:
                    try:
                        elements = await page.locator(selector).all()
                        for el in elements:
                            text = await el.text_content()
                            if text and len(text) > 3:
                                data['teacherAbsences'].append({
                                    'text': text.strip(),
                                    'date': datetime.datetime.now().strftime('%Y-%m-%d')
                                })
                                data['raw_found'].append(f"Absence: {text[:50]}...")
                    except:
                        continue
                
                log_step('info', f"Absences profs trouvées: {len(data['teacherAbsences'])}")
                
                # --- Extraction de la moyenne générale ---
                try:
                    moyenne_el = await page.locator('[class*="moyenne-generale"], .moyenne-gen, [data-moyenne]').first
                    if moyenne_el:
                        moyenne_text = await moyenne_el.text_content()
                        moyenne_match = re.search(r'(\d{1,2}(?:[.,]\d+)?)', moyenne_text)
                        if moyenne_match:
                            data['studentData']['average'] = float(moyenne_match.group(1).replace(',', '.'))
                            log_step('info', f"Moyenne générale: {data['studentData']['average']}")
                except:
                    pass
                
            else:
                log_step('error', "Page Pronote non atteinte")
                data['raw_found'].append(f"Échec: URL finale = {page.url}")
            
            await browser.close()
            log_step('success', "Extraction terminée!")
            
        except Exception as e:
            log_step('error', f"Erreur Playwright: {str(e)}")
            data['raw_found'].append(f"Erreur: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            await browser.close()
    
    return data

def run_async(coro):
    """Helper pour exécuter une coroutine async"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/sync', methods=['POST'])
def sync():
    try:
        req = request.json
        username = req.get('username', '')
        password = req.get('password', '')
        
        log_step('start', "=" * 50)
        log_step('start', "NOUVELLE SYNCHRONISATION PLAYWRIGHT")
        log_step('start', "=" * 50)
        log_step('info', f"Utilisateur: {username.split('@')[0]}***")
        log_step('info', f"École: {CONFIG['SCHOOL_NAME']}")
        log_step('info', f"URL: {CONFIG['SCHOOL_URL']}")
        
        if not username or not password:
            log_step('error', "Identifiants manquants!")
            return jsonify({'error': 'Identifiants requis', 'auth_success': False}), 400
        
        # Exécuter le scraping avec Playwright
        result = run_async(scrape_with_playwright(username, password))
        
        log_step('success', "=" * 50)
        log_step('success', "FIN DE SYNCHRONISATION")
        log_step('info', f"Auth: {'✅ Réussie' if result['auth_success'] else '❌ Échouée'}")
        log_step('info', f"Élève: {result['studentData']['name'] or 'Non trouvé'}")
        log_step('info', f"Classe: {result['studentData']['class'] or 'Non trouvée'}")
        log_step('info', f"Cours: {sum(len(day) for day in result['schedule'])}")
        log_step('info', f"Devoirs: {len(result['homework'])}")
        log_step('info', f"Notes: {len(result['grades'])}")
        log_step('success', "=" * 50)
        
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
        'version': '3.0-playwright',
        'school': CONFIG['SCHOOL_NAME']
    })

@app.route('/')
def home():
    return jsonify({
        'name': 'Pronote Bridge Server (Playwright)',
        'version': '3.0',
        'school': CONFIG['SCHOOL_NAME'],
        'endpoints': {
            '/health': 'GET - Health check',
            '/sync': 'POST - Synchronisation Pronote (username, password)'
        },
        'features': [
            'Navigateur automatisé (simule un vrai utilisateur)',
            'Extraction emploi du temps',
            'Extraction devoirs',
            'Extraction notes',
            'Détection profs absents'
        ],
        'status': 'running'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Démarrage du serveur Pronote Bridge (Playwright) sur le port {port}")
    app.run(host='0.0.0.0', port=port)
