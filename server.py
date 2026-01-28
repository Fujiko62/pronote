import os
import re
import logging
import asyncio
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.async_api import async_playwright

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = {
    'SCHOOL_URL': 'https://0771068t.index-education.net/pronote/',
    'SCHOOL_NAME': 'Collège Les Creuzets'
}

def log_step(step, message):
    logger.info(f"[{step.upper()}] {message}")

async def scrape(username, password):
    data = {'auth_success': False, 'schedule': [[], [], [], [], []]}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            log_step('browser', 'Navigation vers Pronote...')
            await page.goto(f"{CONFIG['SCHOOL_URL']}eleve.html")
            
            # Login ENT
            if 'ent' in page.url:
                log_step('auth', 'Login ENT...')
                await page.fill('input[type="email"], input[name="email"], input[name="username"]', username)
                await page.fill('input[type="password"]', password)
                await page.click('button[type="submit"], input[type="submit"]')
                await page.wait_for_load_state('networkidle')
            
            # Clic sur Pronote si nécessaire
            if 'pronote' not in page.url:
                log_step('nav', 'Recherche lien Pronote...')
                try:
                    await page.click('text=Pronote', timeout=5000)
                except:
                    pass
            
            # Extraction
            if 'pronote' in page.url:
                data['auth_success'] = True
                log_step('extract', 'Extraction...')
                
                # Emploi du temps
                elements = await page.locator('.sr-only').all_text_contents()
                day_idx = datetime.datetime.now().weekday()
                if day_idx > 4: day_idx = 0
                
                for text in elements:
                    if 'de' in text and 'à' in text:
                        data['schedule'][day_idx].append({'text': text})
                        
        except Exception as e:
            log_step('error', str(e))
        finally:
            await browser.close()
            
    return data

@app.route('/sync', methods=['POST'])
def sync():
    req = request.json
    username = req.get('username')
    password = req.get('password')
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(scrape(username, password))
    
    return jsonify(result)

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '6.0-playwright'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
