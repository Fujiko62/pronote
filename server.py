import os
import re
import logging
import datetime
import asyncio
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Logs détaillés
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
logger = logging.getLogger(__name__)

# Configuration école
CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message):
    icons = {'start': '🚀', 'browser': '🌐', 'auth': '🔐', 'click': '👆', 'type': '⌨️', 'wait': '⏳', 'extract': '🔍', 'success': '✅', 'error': '❌', 'info': 'ℹ️'}
    logger.info(f"{icons.get(step, '📌')} [{step.upper()}] {message}")

async def scrape_pronote(username, password):
    """Utilise un VRAI navigateur Chrome pour se connecter comme un élève"""
    from playwright.async_api import async_playwright
    
    result = {
        'studentData': {'name': '', 'class': '', 'average': None},
        'schedule': [[], [], [], [], []],
        'homework': [],
        'grades': [],
        'messages': [],
        'auth_success': False,
        'raw_found': []
    }
    
    async with async_playwright() as p:
        log_step('browser', 'Lancement de Chrome...')
        
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        page = await browser.new_page()
        page.set_default_timeout(30000)
        
        try:
            # === ÉTAPE 1: Aller sur Pronote ===
            log_step('browser', f"Navigation vers {CONFIG['SCHOOL_URL']}eleve.html")
            await page.goto(f"{CONFIG['SCHOOL_URL']}eleve.html")
            await page.wait_for_load_state('networkidle')
            
            log_step('info', f"URL actuelle: {page.url}")
            result['raw_found'].append(f"URL après Pronote: {page.url}")
            
            # === ÉTAPE 2: On est sur l'ENT, chercher le formulaire ===
            if 'ent' in page.url.lower() or 'seine-et-marne' in page.url.lower():
                log_step('auth', "Page ENT détectée, recherche du formulaire...")
                
                # Attendre que la page charge complètement
                await asyncio.sleep(2)
                
                # Chercher le champ email/identifiant
                email_input = None
                for selector in ['input[name="email"]', 'input[name="username"]', 'input[type="email"]', 'input[id="email"]', 'input[id="username"]', '#email', '#username']:
                    try:
                        if await page.locator(selector).count() > 0:
                            email_input = selector
                            log_step('success', f"Champ identifiant trouvé: {selector}")
                            break
                    except:
                        continue
                
                # Chercher le champ mot de passe
                password_input = None
                for selector in ['input[name="password"]', 'input[type="password"]', 'input[id="password"]', '#password']:
                    try:
                        if await page.locator(selector).count() > 0:
                            password_input = selector
                            log_step('success', f"Champ mot de passe trouvé: {selector}")
                            break
                    except:
                        continue
                
                if email_input and password_input:
                    # Remplir les champs
                    log_step('type', f"Saisie identifiant: {username[:10]}***")
                    await page.fill(email_input, username)
                    
                    log_step('type', "Saisie mot de passe: ********")
                    await page.fill(password_input, password)
                    
                    # Chercher et cliquer sur le bouton de connexion
                    submit_clicked = False
                    for selector in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Connexion")', 'button:has-text("Se connecter")', '.btn-primary', '#submit']:
                        try:
                            if await page.locator(selector).count() > 0:
                                log_step('click', f"Clic sur: {selector}")
                                await page.click(selector)
                                submit_clicked = True
                                break
                        except:
                            continue
                    
                    if submit_clicked:
                        log_step('wait', "Attente après connexion...")
                        await page.wait_for_load_state('networkidle')
                        await asyncio.sleep(3)
                        
                        log_step('info', f"URL après login: {page.url}")
                        result['raw_found'].append(f"URL après login: {page.url}")
                        
                        # Vérifier si on est toujours sur login (erreur)
                        if 'login' in page.url.lower() and 'error' in page.url.lower():
                            log_step('error', "Identifiants incorrects!")
                            await browser.close()
                            return result
                else:
                    log_step('error', "Champs de login non trouvés!")
                    result['raw_found'].append("Champs login non trouvés")
            
            # === ÉTAPE 3: Chercher le lien Pronote si on est sur le portail ENT ===
            if 'pronote' not in page.url.lower() and 'index-education' not in page.url.lower():
                log_step('browser', "Recherche du lien Pronote...")
                
                # Chercher un lien vers Pronote
                for selector in ['a:has-text("Pronote")', 'a:has-text("PRONOTE")', 'a[href*="pronote"]', 'a[href*="index-education"]', '[data-app*="pronote"]']:
                    try:
                        if await page.locator(selector).count() > 0:
                            log_step('click', f"Clic sur Pronote: {selector}")
                            await page.click(selector)
                            await page.wait_for_load_state('networkidle')
                            await asyncio.sleep(2)
                            log_step('info', f"URL après clic Pronote: {page.url}")
                            break
                    except:
                        continue
            
            # === ÉTAPE 4: Vérifier qu'on est sur Pronote ===
            current_url = page.url
            log_step('info', f"URL finale: {current_url}")
            
            if 'pronote' in current_url.lower() or 'index-education' in current_url.lower():
                result['auth_success'] = True
                log_step('success', "PAGE PRONOTE ATTEINTE!")
                
                # Attendre que Pronote charge
                await asyncio.sleep(2)
                
                # === EXTRACTION DES DONNÉES ===
                
                # 1. Nom de l'élève (depuis le titre)
                title = await page.title()
                log_step('extract', f"Titre: {title}")
                result['raw_found'].append(f"Titre: {title}")
                
                if title and '-' in title:
                    for part in title.split('-'):
                        clean = part.strip().replace('ESPACE ÉLÈVE', '').replace('PRONOTE', '').strip()
                        if clean and len(clean) > 2:
                            result['studentData']['name'] = clean
                            log_step('success', f"Nom trouvé: {clean}")
                            break
                
                # 2. Récupérer tout le contenu de la page
                content = await page.content()
                log_step('info', f"Taille page: {len(content)} bytes")
                
                # 3. Chercher la classe
                class_match = re.search(r'(\d+(?:ème|EME|e|è)\s*[A-Z0-9]?)', content, re.I)
                if class_match:
                    result['studentData']['class'] = class_match.group(1).upper()
                    log_step('success', f"Classe: {result['studentData']['class']}")
                
                # 4. Chercher l'emploi du temps (balises sr-only)
                day_idx = datetime.datetime.now().weekday()
                if day_idx > 4:
                    day_idx = 0
                
                # Récupérer tous les textes sr-only
                sr_only_texts = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('.sr-only, [class*="sr-only"]'))
                        .map(el => el.textContent.trim())
                        .filter(t => t.length > 5);
                }''')
                
                log_step('extract', f"Textes sr-only trouvés: {len(sr_only_texts)}")
                
                for text in sr_only_texts:
                    match = re.search(r"de\s+(\d{1,2}h\d{2})\s+à\s+(\d{1,2}h\d{2})\s+(.+)", text, re.I)
                    if match:
                        subject = match.group(3).strip()
                        if 'pause' not in subject.lower() and 'récré' not in subject.lower():
                            course = {
                                'time': f"{match.group(1).replace('h', ':')} - {match.group(2).replace('h', ':')}",
                                'subject': subject,
                                'teacher': '',
                                'room': 'Salle'
                            }
                            result['schedule'][day_idx].append(course)
                            result['raw_found'].append(f"Cours: {subject}")
                            log_step('success', f"Cours trouvé: {subject}")
                
                log_step('info', f"Cours aujourd'hui: {len(result['schedule'][day_idx])}")
                
                # 5. Chercher les devoirs
                homework_texts = await page.evaluate('''() => {
                    const keywords = ['devoir', 'travail', 'exercice', 'pour le', 'à faire'];
                    return Array.from(document.querySelectorAll('div, li, p, span'))
                        .map(el => el.textContent.trim())
                        .filter(t => t.length > 20 && t.length < 500)
                        .filter(t => keywords.some(k => t.toLowerCase().includes(k)))
                        .slice(0, 10);
                }''')
                
                for i, text in enumerate(homework_texts):
                    result['homework'].append({
                        'id': i + 1,
                        'subject': 'À déterminer',
                        'title': text[:100],
                        'dueDate': datetime.datetime.now().strftime('%Y-%m-%d'),
                        'done': False,
                        'description': text
                    })
                
                log_step('info', f"Devoirs trouvés: {len(result['homework'])}")
                
                # 6. Chercher les notes
                grade_texts = await page.evaluate('''() => {
                    const pattern = /\\d{1,2}([.,]\\d+)?\\s*\\/\\s*\\d{1,2}/;
                    return Array.from(document.querySelectorAll('*'))
                        .map(el => el.textContent.trim())
                        .filter(t => pattern.test(t) && t.length < 100)
                        .slice(0, 20);
                }''')
                
                for text in grade_texts:
                    match = re.search(r'(\d{1,2}(?:[.,]\d+)?)\s*/\s*(\d{1,2})', text)
                    if match:
                        try:
                            grade = float(match.group(1).replace(',', '.'))
                            out_of = int(match.group(2))
                            if 0 <= grade <= out_of <= 20:
                                result['grades'].append({
                                    'subject': 'Matière',
                                    'grade': grade,
                                    'outOf': out_of,
                                    'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                                    'title': text[:50]
                                })
                        except:
                            pass
                
                log_step('info', f"Notes trouvées: {len(result['grades'])}")
                
            else:
                log_step('error', f"Pas sur Pronote! URL: {current_url}")
                result['raw_found'].append(f"Échec - URL finale: {current_url}")
        
        except Exception as e:
            log_step('error', f"Erreur: {str(e)}")
            result['raw_found'].append(f"Erreur: {str(e)}")
        
        finally:
            await browser.close()
            log_step('browser', "Navigateur fermé")
    
    return result

@app.route('/sync', methods=['POST'])
def sync():
    try:
        data = request.json
        username = data.get('username', '')
        password = data.get('password', '')
        
        log_step('start', "=" * 50)
        log_step('start', "NOUVELLE SYNCHRONISATION")
        log_step('start', "=" * 50)
        log_step('info', f"Utilisateur: {username[:15]}***")
        
        if not username or not password:
            return jsonify({'error': 'Identifiants requis', 'auth_success': False}), 400
        
        # Lancer le scraping
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(scrape_pronote(username, password))
        loop.close()
        
        log_step('success', "=" * 50)
        log_step('info', f"Auth: {'✅' if result['auth_success'] else '❌'}")
        log_step('info', f"Élève: {result['studentData']['name']}")
        log_step('info', f"Cours: {sum(len(d) for d in result['schedule'])}")
        log_step('success', "=" * 50)
        
        return jsonify(result)
    
    except Exception as e:
        log_step('error', f"Erreur: {str(e)}")
        return jsonify({'error': str(e), 'auth_success': False}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '3.0-playwright', 'school': CONFIG['SCHOOL_NAME']})

@app.route('/')
def home():
    return jsonify({'name': 'Pronote Bridge (Chrome)', 'status': 'running 🚀', 'method': 'Playwright/Chrome'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Serveur Playwright sur port {port}")
    app.run(host='0.0.0.0', port=port)
