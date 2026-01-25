from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging
import re

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def login_ent_seine_et_marne(username, password, pronote_url):
    """Authentification ENT Seine-et-Marne"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    logger.info("=== Auth ENT Seine-et-Marne ===")
    
    try:
        # Etape 1: Acces Pronote
        resp1 = session.get(pronote_url, allow_redirects=True)
        parsed_url = urlparse(resp1.url)
        callback = parse_qs(parsed_url.query).get('callback', [''])[0]
        
        # Etape 2: Parser formulaire
        soup = BeautifulSoup(resp1.text, 'html.parser')
        form = soup.find('form')
        if not form:
            return None
        
        action = form.get('action', '')
        form_data = {'email': username, 'password': password}
        
        # URL avec callback
        if callback:
            action_url = f"{action}?callback={callback}"
        else:
            action_url = action
        
        logger.info(f"POST vers {action_url}")
        
        # Etape 3: Envoi formulaire
        resp2 = session.post(action_url, data=form_data, allow_redirects=True)
        logger.info(f"URL finale: {resp2.url}")
        
        # Verifier succes
        if 'pronote' in resp2.url.lower() and resp2.status_code == 200:
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
            body = soup2.find('body')
            
            if body and body.get('onload'):
                onload = body.get('onload')
                logger.info(f"onload: {onload[:150]}")
                
                # Extraire les parametres
                match = re.search(r"Start\s*\(\s*\{([^}]+)\}", onload)
                if match:
                    params_str = match.group(1)
                    
                    # Extraire h, e, f
                    h_match = re.search(r"h[:\s]*['\"]?(\d+)['\"]?", params_str)
                    e_match = re.search(r"e[:\s]*['\"]([^'\"]+)['\"]", params_str)
                    f_match = re.search(r"f[:\s]*['\"]([^'\"]+)['\"]", params_str)
                    
                    if h_match and e_match and f_match:
                        return {
                            'session': session,
                            'cookies': session.cookies,
                            'url': resp2.url,
                            'h': int(h_match.group(1)),
                            'e': e_match.group(1),
                            'f': f_match.group(1)
                        }
        return None
    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        logger.info(f"=== SYNCHRO {username} ===")
        
        client = None
        
        # Methode 1: Notre scraping custom
        try:
            logger.info(">>> ENT Seine-et-Marne (custom)")
            auth_result = login_ent_seine_et_marne(username, password, pronote_url)
            
            if auth_result:
                logger.info(f"Auth reussie! h={auth_result['h']}, e={auth_result['e'][:20]}...")
                
                # Creer le client avec les credentials ENT
                # On passe par l'URL avec l'identifiant deja inclus
                client = pronotepy.Client(
                    auth_result['url'],
                    username=auth_result['e'],
                    password=auth_result['f']
                )
                
                if client.logged_in:
                    logger.info(f"✅ CONNECTE: {client.info.name}")
        except Exception as e:
            logger.warning(f"❌ Custom: {str(e)[:100]}")
            client = None
        
        # Methode 2: Utiliser directement l'URL avec identifiant
        if not client or not client.logged_in:
            try:
                logger.info(">>> Methode URL directe")
                auth_result = login_ent_seine_et_marne(username, password, pronote_url)
                
                if auth_result:
                    # L'URL contient deja ?identifiant=xxx
                    # On peut essayer de creer un client directement
                    final_url = auth_result['url']
                    logger.info(f"URL avec identifiant: {final_url}")
                    
                    # Extraire l'identifiant de l'URL
                    parsed = urlparse(final_url)
                    identifiant = parse_qs(parsed.query).get('identifiant', [''])[0]
                    
                    if identifiant:
                        # Construire l'URL sans parametres
                        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        logger.info(f"Base URL: {base_url}, identifiant: {identifiant}")
                        
                        # Le e et f sont les credentials pour cette session
                        client = pronotepy.Client(
                            base_url,
                            username=auth_result['e'],
                            password=auth_result['f']
                        )
                        
                        if client.logged_in:
                            logger.info(f"✅ CONNECTE: {client.info.name}")
            except Exception as e:
                logger.warning(f"❌ URL directe: {str(e)[:100]}")
                client = None

        # Methode 3: ENT standard (fallback)
        if not client or not client.logged_in:
            try:
                logger.info(">>> ent77 standard")
                import pronotepy.ent as ent_module
                if hasattr(ent_module, 'ent77'):
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_module.ent77)
                    if client.logged_in:
                        logger.info(f"✅ CONNECTE via ent77: {client.info.name}")
            except Exception as e:
                logger.warning(f"❌ ent77: {str(e)[:80]}")

        if not client or not client.logged_in:
            return jsonify({'error': 'Echec connexion. Verifiez vos identifiants.'}), 401

        # === RECUPERATION DES DONNEES ===
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0,
                'rank': 1,
                'totalStudents': 30
            },
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': [],
            'subjectAverages': [],
            'messages': []
        }

        # Emploi du temps
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            for day in range(5):
                for l in client.lessons(monday + timedelta(days=day)):
                    result['schedule'][day].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-red-500' if l.canceled else 'bg-indigo-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
            logger.info(f"EDT: {sum(len(d) for d in result['schedule'])} cours")
        except Exception as e:
            logger.error(f"EDT: {e}")

        # Devoirs
        try:
            hws = client.homework(datetime.now(), datetime.now() + timedelta(days=14))
            for i, hw in enumerate(hws):
                result['homework'].append({
                    'id': i,
                    'subject': hw.subject.name if hw.subject else 'Devoir',
                    'title': hw.description,
                    'dueDate': hw.date.strftime('%d/%m'),
                    'urgent': (hw.date - datetime.now().date()).days < 2,
                    'done': getattr(hw, 'done', False),
                    'color': 'bg-indigo-500'
                })
            logger.info(f"Devoirs: {len(result['homework'])}")
        except Exception as e:
            logger.error(f"Devoirs: {e}")

        # Notes
        try:
            period = client.current_period
            total, count = 0, 0
            for g in period.grades[:20]:
                try:
                    val = float(g.grade.replace(',', '.'))
                    mx = float(g.out_of.replace(',', '.'))
                    total += (val/mx)*20
                    count += 1
                    result['grades'].append({
                        'subject': g.subject.name,
                        'grade': val,
                        'max': mx,
                        'date': g.date.strftime('%d/%m'),
                        'comment': g.comment or '',
                        'average': round((val/mx)*20, 1)
                    })
                except: pass
            if count > 0:
                result['studentData']['average'] = round(total/count, 1)
            
            # Moyennes par matiere
            for avg in period.averages:
                try:
                    result['subjectAverages'].append({
                        'subject': avg.subject.name,
                        'average': float(avg.student.replace(',', '.')) if avg.student else 0,
                        'classAvg': float(avg.class_average.replace(',', '.')) if avg.class_average else 0,
                        'color': 'bg-indigo-500',
                        'icon': 'fa-book'
                    })
                except: pass
            logger.info(f"Notes: {len(result['grades'])}, Moy: {result['studentData']['average']}")
        except Exception as e:
            logger.error(f"Notes: {e}")

        logger.info(f"=== FIN SYNCHRO {client.info.name} ===")
        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
