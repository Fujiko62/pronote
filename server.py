from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from pronotepy.ent import ent_77
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        # URL mobile
        if 'eleve.html' in school_url:
            base_url = school_url.split('eleve.html')[0]
        else:
            base_url = school_url if school_url.endswith('/') else school_url + '/'
            
        mobile_url = base_url + 'mobile.eleve.html'
        
        logger.info(f"Tentative MOBILE sur {mobile_url}")
        
        client = None
        
        # Essai 1: ENT 77 Mobile
        try:
            logger.info("Essai ENT 77 Mobile...")
            client = pronotepy.Client(
                mobile_url,
                username=username,
                password=password,
                ent=ent_77
            )
        except Exception as e:
            logger.warning(f"Echec Mobile 1: {e}")
            
        # Essai 2: Connexion Directe Mobile
        if not client:
            try:
                logger.info("Essai Direct Mobile...")
                client = pronotepy.Client(
                    mobile_url,
                    username=username,
                    password=password
                )
            except Exception as e:
                logger.warning(f"Echec Mobile 2: {e}")

        if not client or not client.logged_in:
            return jsonify({'error': 'Echec connexion Mobile'}), 401
            
        logger.info(f"✅ CONNECTE (Mobile): {client.info.name}")
        
        # Recuperation des donnees (API limitee sur mobile)
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0
            },
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': []
        }
        
        # Sur mobile, les fonctions sont differentes
        # On fait au mieux
        
        # EDT
        try:
            from datetime import datetime, timedelta
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            for day in range(5):
                for l in client.lessons(monday + timedelta(days=day)):
                    result['schedule'][day].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-indigo-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
        except Exception as e:
            logger.error(f"Erreur EDT: {e}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
