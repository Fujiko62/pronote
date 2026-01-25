from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
import pronotepy.ent
from datetime import datetime, timedelta
import logging
import functools

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_ent_name_safe(ent):
    """Recupere le nom de l'ENT sans faire planter le serveur"""
    if ent is None:
        return "Connexion Directe"
    if hasattr(ent, '__name__'):
        return ent.__name__
    if isinstance(ent, functools.partial):
        # C'est ici que ca plantait avant, maintenant on gere le cas
        return "ENT_Specifique (Partial)"
    return str(ent)

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        # Nettoyage URL
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        logger.info(f"Tentative de connexion pour {username}")

        # --- SELECTION DES ENT ---
        # On cherche specifiquement ceux du 77 et IDF
        ent_candidates = []
        
        # 1. Chercher ent77 ou ent_77 (Seine-et-Marne)
        if hasattr(pronotepy.ent, 'ent77'):
            ent_candidates.append(getattr(pronotepy.ent, 'ent77'))
        elif hasattr(pronotepy.ent, 'ent_77'):
            ent_candidates.append(getattr(pronotepy.ent, 'ent_77'))
            
        # 2. Chercher ile_de_france
        if hasattr(pronotepy.ent, 'ile_de_france'):
            ent_candidates.append(getattr(pronotepy.ent, 'ile_de_france'))
            
        # 3. Ajouter la connexion directe (fallback)
        ent_candidates.append(None)

        client = None
        
        for ent in ent_candidates:
            ent_name = get_ent_name_safe(ent)
            try:
                logger.info(f"Essai avec : {ent_name}...")
                if ent:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    logger.info(f"✅ CONNECTE via {ent_name}!")
                    break
            except Exception as e:
                logger.warning(f"❌ Echec {ent_name}: {str(e)[:100]}")
                client = None

        if not client or not client.logged_in:
            return jsonify({'error': 'Echec de connexion. Verifiez vos identifiants ou l\'URL.'}), 401

        # --- RECUPERATION DES DONNEES ---
        
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

        # Notes et Moyenne
        try:
            period = client.current_period
            grades = sorted(period.grades, key=lambda g: g.date, reverse=True)
            total = 0
            count = 0
            
            for g in grades[:20]:
                try:
                    val = float(g.grade.replace(',', '.'))
                    mx = float(g.out_of.replace(',', '.'))
                    normalized = (val / mx) * 20
                    total += normalized
                    count += 1
                    
                    result['grades'].append({
                        'subject': g.subject.name,
                        'grade': val,
                        'max': mx,
                        'date': g.date.strftime('%d/%m'),
                        'comment': g.comment or '',
                        'average': round(normalized, 1)
                    })
                except: pass
            
            if count > 0:
                result['studentData']['average'] = round(total / count, 1)

            # Moyennes matieres
            for avg in period.averages:
                try:
                    student_avg = float(avg.student.replace(',', '.')) if avg.student else 0
                    class_avg = float(avg.class_average.replace(',', '.')) if avg.class_average else 0
                    result['subjectAverages'].append({
                        'subject': avg.subject.name,
                        'average': student_avg,
                        'classAvg': class_avg,
                        'color': 'bg-indigo-500',
                        'icon': 'fa-book'
                    })
                except: pass

        except Exception as e:
             logger.error(f"Erreur Notes: {e}")

        logger.info(f"Synchro terminee pour {client.info.name}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur generale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
