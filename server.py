from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from datetime import datetime, timedelta
import functools

app = Flask(__name__)
CORS(app)

def get_available_ents():
    """Recupere les ENT disponibles dans pronotepy de facon robuste"""
    ent_list = [None]
    try:
        import pronotepy.ent as ent_module
        ent_names = [
            'ile_de_france', 'paris_classe_numerique', 'monlycee_net',
            'ent_somme', 'ac_reunion', 'ac_reims', 'occitanie_montpellier',
            'cas_agora06', 'eclat_bfc', 'laclasse_lyon', 'ent_mayotte',
            'ent_hdf', 'ent_var', 'atrium_sud', 'ac_orleans_tours',
            'ac_poitiers', 'ac_rennes', 'neoconnect_guadeloupe',
            'pronote_hubeduconnect', 'ent_77'
        ]
        for name in ent_names:
            if hasattr(ent_module, name):
                ent_list.append(getattr(ent_module, name))
    except Exception as e:
        print(f"Erreur chargement ENT: {e}")
    return ent_list

def get_ent_display_name(ent):
    """Retourne le nom de l'ENT de facon securisee"""
    if ent is None:
        return "Direct (sans ENT)"
    if hasattr(ent, '__name__'):
        return ent.__name__
    if isinstance(ent, functools.partial):
        return f"Partial({ent.func.__name__})"
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
        
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        pronote_url = school_url + 'eleve.html'
        
        print(f"\n{'='*60}\nTENTATIVE: {username} sur {pronote_url}\n{'='*60}")
        
        client = None
        used_ent_name = None
        ent_list = get_available_ents()
        
        for ent in ent_list:
            ent_name = get_ent_display_name(ent)
            try:
                print(f"  Essai: {ent_name}...")
                if ent:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    print(f"  ✅ SUCCES avec {ent_name}!")
                    used_ent_name = ent_name
                    break
                client = None
            except Exception as e:
                print(f"  ❌ Echec {ent_name}: {str(e)[:60]}")
                client = None
                continue
        
        if not client or not client.logged_in:
            return jsonify({'error': 'Connexion impossible. Verifiez vos identifiants.'}), 401
        
        # Données de base
        result = {
            'studentData': {
                'name': client.info.name,
                'class': client.info.class_name,
                'average': 0
            },
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': [],
            'subjectAverages': [],
            'messages': []
        }
        
        # Recup Emploi du temps
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            for day in range(5):
                current = monday + timedelta(days=day)
                lessons = client.lessons(current, current)
                for lesson in lessons:
                    subj = lesson.subject.name if lesson.subject else 'Cours'
                    result['schedule'][day].append({
                        'time': f"{lesson.start.strftime('%H:%M')} - {lesson.end.strftime('%H:%M')}",
                        'subject': subj,
                        'teacher': lesson.teacher_name or '',
                        'room': lesson.classroom or '',
                        'color': 'bg-indigo-500'
                    })
                result['schedule'][day].sort(key=lambda x: x['time'])
        except: pass

        # Recup Devoirs
        try:
            for i, hw in enumerate(client.homework(datetime.now(), datetime.now() + timedelta(days=14))[:12]):
                result['homework'].append({
                    'id': i + 1,
                    'subject': hw.subject.name if hw.subject else 'Devoir',
                    'title': hw.description or '',
                    'dueDate': hw.date.strftime('%d/%m'),
                    'urgent': i < 2,
                    'done': getattr(hw, 'done', False),
                    'color': 'bg-indigo-500'
                })
        except: pass

        # Recup Notes
        try:
            total, count = 0, 0
            for period in client.periods:
                for grade in period.grades:
                    try:
                        val = float(str(grade.grade).replace(',', '.'))
                        mx = float(str(grade.out_of).replace(',', '.')) if grade.out_of else 20
                        total += (val / mx) * 20
                        count += 1
                        result['grades'].append({
                            'subject': grade.subject.name,
                            'grade': val,
                            'max': mx,
                            'date': grade.date.strftime('%d/%m'),
                            'comment': grade.comment or '',
                            'average': val
                        })
                    except: pass
                break
            if count > 0:
                result['studentData']['average'] = round(total / count, 1)
        except: pass
        
        print(f"🎉 Synchro terminee pour {client.info.name}")
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur generale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

@app.route('/')
def home(): return "Pronote Sync Server is Running"

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
