from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import pronotepy.ent
from datetime import datetime, timedelta
import logging
import functools

app = Flask(__name__)
CORS(app)

# Configuration logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_ent_by_name(name):
    """Récupère une fonction ENT par son nom sans planter"""
    try:
        if hasattr(pronotepy.ent, name):
            return getattr(pronotepy.ent, name)
    except: pass
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
        
        # Nettoyage de l'URL
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        logger.info(f"Tentative de synchronisation pour {username} sur {pronote_url}")
        
        client = None
        
        # Liste des ENT à tester (noms exacts dans pronotepy)
        # On met en premier ceux du 77 et IDF
        ent_names_to_try = [
            'ent_77', 
            'ile_de_france', 
            'monlycee_net', 
            'paris_classe_numerique',
            'educonnect',
            'cas_agora06',
            'ent_auvergnerhonealpes',
            'ent_essonne',
            'ent_somme'
        ]

        # 1. Tester les ENT spécifiques
        for ent_name in ent_names_to_try:
            ent_func = get_ent_by_name(ent_name)
            if not ent_func:
                continue
                
            try:
                logger.info(f"Essai avec ENT: {ent_name}...")
                client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                if client.logged_in:
                    logger.info(f"✅ Connecte avec succes via {ent_name}")
                    break
                client = None
            except Exception as e:
                logger.warning(f"❌ Echec {ent_name}: {str(e)[:50]}")
                client = None

        # 2. Si echec, tester sans ENT (Direct)
        if not client:
            try:
                logger.info("Essai connexion DIRECTE (sans ENT)...")
                client = pronotepy.Client(pronote_url, username=username, password=password)
                if client.logged_in:
                    logger.info("✅ Connecte avec succes en DIRECT")
            except Exception as e:
                logger.warning(f"❌ Echec Direct: {str(e)[:50]}")

        if not client or not client.logged_in:
            return jsonify({'error': 'Connexion impossible. Verifiez identifiant/mot de passe.'}), 401

        # --- RECUPERATION DES DONNEES ---
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0,
                'rank': 1,
                'totalStudents': 28
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
                lessons = client.lessons(monday + timedelta(days=day))
                for l in lessons:
                    result['schedule'][day].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-indigo-500' if not l.canceled else 'bg-red-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
        except Exception as e:
            logger.error(f"Erreur EDT: {e}")

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
        except Exception as e:
            logger.error(f"Erreur Devoirs: {e}")

        # Notes
        try:
            period = client.current_period
            grades = sorted(period.grades, key=lambda g: g.date, reverse=True)
            for g in grades[:20]:
                val = float(g.grade.replace(',', '.'))
                mx = float(g.out_of.replace(',', '.'))
                result['grades'].append({
                    'subject': g.subject.name,
                    'grade': val,
                    'max': mx,
                    'date': g.date.strftime('%d/%m'),
                    'comment': g.comment or '',
                    'average': val
                })
            
            # Moyenne generale
            if period.overall_average:
                result['studentData']['average'] = float(period.overall_average.replace(',', '.'))
                
        except Exception as e:
            logger.error(f"Erreur Notes: {e}")

        logger.info(f"✅ Synchro terminee pour {client.info.name}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur generale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

@app.route('/')
def home(): return "Pronote Sync Server Running"

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
