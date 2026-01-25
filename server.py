from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from pronotepy.ent import ent_77, ile_de_france, educonnect
from datetime import datetime, timedelta
import logging

app = Flask(__name__)
CORS(app)

# Configuration des logs pour voir precisement ce qui se passe sur Render
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        # Nettoyage de l'URL pour pronotepy
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        logger.info(f"Tentative de synchronisation pour {username} sur {pronote_url}")
        
        client = None
        # On teste les 3 modes les plus probables pour le 77
        modes = [
            ("ENT Seine-et-Marne", ent_77),
            ("EduConnect", educonnect),
            ("Ile-de-France", ile_de_france),
            ("Direct", None)
        ]
        
        last_error = ""
        for mode_name, ent_func in modes:
            try:
                logger.info(f"Essai du mode : {mode_name}")
                if ent_func:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent_func)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    logger.info(f"✅ Connecte avec succes via {mode_name}")
                    break
                client = None
            except Exception as e:
                last_error = str(e)
                logger.warning(f"❌ Echec {mode_name}: {last_error[:100]}")
                client = None

        if not client or not client.logged_in:
            return jsonify({'error': f"Identifiants incorrects ou ENT non supporte. (Derniere erreur: {last_error[:50]})"}), 401

        # --- RECUPERATION DES DONNEES ---
        
        # 1. Infos de base
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

        # 2. Emploi du temps (Semaine actuelle)
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            friday = monday + timedelta(days=4)
            
            lessons = client.lessons(monday, friday)
            for l in lessons:
                # Determiner le jour (0=Lundi, etc.)
                day_idx = l.start.weekday()
                if 0 <= day_idx <= 4:
                    result['schedule'][day_idx].append({
                        'time': f"{l.start.strftime('%H:%M')} - {l.end.strftime('%H:%M')}",
                        'subject': l.subject.name if l.subject else 'Cours',
                        'teacher': l.teacher_name or '',
                        'room': l.classroom or '',
                        'color': 'bg-red-500' if l.canceled else 'bg-indigo-500'
                    })
            # Trier par heure
            for day in range(5):
                result['schedule'][day].sort(key=lambda x: x['time'])
        except Exception as e:
            logger.error(f"Erreur emploi du temps: {e}")

        # 3. Devoirs
        try:
            hws = client.homework(datetime.now(), datetime.now() + timedelta(days=10))
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
            logger.error(f"Erreur devoirs: {e}")

        # 4. Notes et Moyennes
        try:
            total_sum = 0
            total_count = 0
            # On prend les notes de la periode actuelle
            period = client.current_period
            for grade in period.grades:
                try:
                    val = float(grade.grade.replace(',', '.'))
                    out_of = float(grade.out_of.replace(',', '.'))
                    norm_grade = (val / out_of) * 20
                    total_sum += norm_grade
                    total_count += 1
                    
                    result['grades'].append({
                        'subject': grade.subject.name,
                        'grade': val,
                        'max': out_of,
                        'date': grade.date.strftime('%d/%m'),
                        'comment': grade.comment or '',
                        'average': round(norm_grade, 1)
                    })
                except: continue
            
            if total_count > 0:
                result['studentData']['average'] = round(total_sum / total_count, 1)
                
            # Moyennes par matiere
            for avg in period.averages:
                result['subjectAverages'].append({
                    'subject': avg.subject.name,
                    'average': float(avg.student.replace(',', '.')) if avg.student else 0,
                    'classAvg': float(avg.class_average.replace(',', '.')) if avg.class_average else 0,
                    'color': 'bg-indigo-500',
                    'icon': 'fa-book'
                })
        except Exception as e:
            logger.error(f"Erreur notes: {e}")

        logger.info(f"✅ Synchronisation terminee pour {client.info.name}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur generale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/')
def home():
    return "Pronote Sync Server is Active"

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
