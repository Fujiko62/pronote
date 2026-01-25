from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from pronotepy.ent.generic_func import _cas, _open_ent_ng
from functools import partial
from datetime import datetime, timedelta
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# CREATION D'ENT PERSONNALISES POUR SEINE-ET-MARNE
# Essayons avec CAS au lieu de Open ENT NG
ent_77_cas = partial(_cas, url="https://ent77.seine-et-marne.fr/cas/login")
ent_77_cas_new = partial(_cas, url="https://ent.seine-et-marne.fr/cas/login")
ent_77_open = partial(_open_ent_ng, url="https://ent.seine-et-marne.fr/auth/login")

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
        
        logger.info(f"=== SYNCHRO pour {username} ===")
        logger.info(f"URL: {pronote_url}")

        client = None
        last_error = ""
        
        # Liste des methodes d'authentification a tester
        ent_methods = [
            ('CAS ent77.seine-et-marne.fr', ent_77_cas),
            ('CAS ent.seine-et-marne.fr', ent_77_cas_new),
            ('Open ENT ent.seine-et-marne.fr', ent_77_open),
        ]
        
        # Ajouter les ENT standards de pronotepy
        import pronotepy.ent as ent_module
        if hasattr(ent_module, 'ent77'):
            ent_methods.append(('ent77 (pronotepy)', ent_module.ent77))
        if hasattr(ent_module, 'ile_de_france'):
            ent_methods.append(('ile_de_france', ent_module.ile_de_france))
        
        # Connexion directe en dernier
        ent_methods.append(('Direct', None))

        for ent_name, ent_func in ent_methods:
            try:
                logger.info(f">>> Essai : {ent_name}")
                if ent_func:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    logger.info(f"✅ CONNECTE via {ent_name}!")
                    break
                client = None
            except Exception as e:
                last_error = str(e)
                logger.warning(f"❌ {ent_name}: {last_error[:100]}")
                client = None

        if not client or not client.logged_in:
            return jsonify({'error': f'Echec. {last_error[:80]}'}), 401

        # --- DONNEES ---
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
            for i, hw in enumerate(client.homework(datetime.now(), datetime.now() + timedelta(days=14))):
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
            logger.info(f"Notes: {len(result['grades'])}")
        except Exception as e:
            logger.error(f"Notes: {e}")

        logger.info(f"=== FIN {client.info.name} ===")
        return jsonify(result)

    except Exception as e:
        logger.error(f"ERREUR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
