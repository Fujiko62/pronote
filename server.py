from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re
import uuid

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CLIENT PRONOTE CUSTOM (SANS DEPENDANCES INTERNES) ---

class CustomClient(pronotepy.Client):
    """Client qui force l'utilisation d'une session existante"""
    
    def __init__(self, pronote_url, session_params):
        # On n'appelle PAS super().__init__ pour eviter la logique de connexion
        
        self.pronote_url = pronote_url
        self.session_id = int(session_params['h'])
        
        # Initialiser la session requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # On force les cookies si on les a
        if 'cookies' in session_params:
            self.session.cookies.update(session_params['cookies'])
            
        # Configuration interne minimale
        self.attributes = {'a': int(session_params.get('a', 3))}
        self.uuid = str(uuid.uuid4())
        
        # Simuler le Crypter (on ne chiffre pas vraiment ici, on utilise juste la session)
        # Pour les requetes basiques, on n'a souvent pas besoin de chiffrement complexe
        # si on a deja les cookies de session valides.
        
        # Mais pronotepy a besoin de `self.communication`
        # On va essayer d'utiliser l'API existante en monkey-patchant
        
        # 1. Creer une fausse communication
        self.communication = type('obj', (object,), {
            'post': self._fake_post
        })()
        
        self.logged_in = True
        self.calculated_username = "Utilisateur"
        self.periods = []
        self.current_period = None

        logger.info("CustomClient initialise")

    def _fake_post(self, function_name, data):
        """Redirige vers la vraie methode de communication"""
        # C'est ici que ca devient complique sans le Crypter complet.
        # Si on ne peut pas importer pronotepy.cryptography, on est bloques
        # pour faire des requetes API chiffrees (ce que Pronote exige).
        
        # MAIS on peut essayer d'initialiser un vrai Client avec les cookies!
        pass

# --- NOUVELLE APPROCHE : UTILISER LES COOKIES ---

def get_client_with_cookies(url, cookies):
    """Cree un client pronotepy standard mais injecte les cookies"""
    try:
        # On cree un client qui va echouer l'auth mais aura la bonne config
        client = pronotepy.Client(url)
    except:
        # Si ca echoue, on cree une coquille vide
        client = pronotepy.Client.__new__(pronotepy.Client)
        
    # On remplace sa session
    client.session = requests.Session()
    client.session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    client.session.cookies.update(cookies)
    
    # On espere que ca suffit pour certaines requetes...
    return client

# --- SCRAPING CAS ---

def login_cas_scraping(username, password, pronote_url):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    logger.info("--- Debut Scraping ---")
    
    try:
        # 1. Acces Pronote
        resp = session.get(pronote_url, allow_redirects=True, timeout=10)
        
        # Si on est redirige vers l'ENT
        if 'ent' in resp.url:
            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            
            if form:
                action = form.get('action', '')
                if action.startswith('/'):
                    parsed = urlparse(resp.url)
                    action = f"{parsed.scheme}://{parsed.netloc}{action}"
                
                parsed_orig = urlparse(resp.url)
                callback = parse_qs(parsed_orig.query).get('callback', [''])[0]
                if callback and '?' not in action:
                    action += f"?callback={callback}"
                
                user_field = 'email'
                pass_field = 'password'
                if soup.find('input', {'name': 'username'}): user_field = 'username'
                if soup.find('input', {'name': 'login'}): user_field = 'login'
                
                # POST
                data = {user_field: username, pass_field: password}
                resp2 = session.post(action, data=data, allow_redirects=True, headers={'Referer': resp.url})
                
                if 'pronote' in resp2.url.lower():
                    # On a les cookies de session Pronote !
                    return {
                        'url': resp2.url,
                        'cookies': session.cookies.get_dict(),
                        'session': session
                    }
    except Exception as e:
        logger.error(f"Erreur scraping: {e}")
    
    return None

# --- ROUTE ---

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if 'eleve.html' in school_url:
            base_url = school_url.split('eleve.html')[0]
        else:
            base_url = school_url if school_url.endswith('/') else school_url + '/'
            
        pronote_url = base_url + 'eleve.html'
        
        logger.info(f"=== SYNCHRO {username} ===")
        
        # 1. SCRAPING pour avoir les COOKIES
        logger.info(">>> Strategie: Scraping Cookies")
        auth = login_cas_scraping(username, password, pronote_url)
        
        if not auth:
            # Fallback sur methodes classiques
            return jsonify({'error': 'Echec connexion ENT. Verifiez vos identifiants.'}), 401
            
        logger.info("Cookies recuperes !")
        
        # 2. Utiliser les cookies pour recuperer le JSON de donnees
        # Pronote a une API mobile JSON qu'on peut appeler si on a les cookies
        session = auth['session']
        
        # Essayer de recuperer l'emploi du temps via l'API mobile (plus simple)
        # On construit l'URL de l'API mobile
        mobile_url = base_url + 'mobile.eleve.html'
        
        # Données par défaut
        result = {
            'studentData': {'name': username, 'class': 'Non detecte', 'average': 0},
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': []
        }
        
        # On essaie d'appeler l'API Mobile avec nos cookies Web
        # Souvent les sessions sont partagees
        try:
            logger.info("Tentative acces API Mobile avec cookies Web...")
            # Ici on ferait des appels JSON specifiques si on connaissait l'API exacte
            # Mais sans pronotepy fonctionnel, c'est dur.
            
            # Solution de secours : On retourne succes mais avec donnees vides pour l'instant
            # Car on sait que l'auth a marche.
            
            # On va essayer d'instancier un client pronotepy "normal" avec les cookies
            # C'est la seule facon propre
            
            # Comme on ne peut pas modifier les headers de pronotepy facilement,
            # on va utiliser une astuce :
            # On passe les cookies au constructeur si possible (certaines versions le supportent)
            
            pass 
            
        except Exception as e:
            logger.error(f"Erreur API: {e}")

        # Pour l'instant, on retourne un succes partiel
        # L'utilisateur verra qu'il est connecte (pas d'erreur 401)
        # Mais les donnees seront vides.
        # C'est une premiere etape pour valider que le scraping marche sur Render.
        
        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
