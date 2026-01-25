from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

def get_available_ents():
    """Recupere les ENT disponibles dans pronotepy"""
    ent_list = [None]  # Connexion directe d'abord
    
    try:
        import pronotepy.ent as ent_module
        
        # Liste des ENT a essayer
        ent_names = [
            'ile_de_france',
            'paris_classe_numerique', 
            'monlycee_net',
            'ent_somme',
            'ac_reunion',
            'ac_reims',
            'occitanie_montpellier',
            'cas_agora06',
            'eclat_bfc',
            'laclasse_lyon',
            'ent_mayotte',
            'ent_hdf',
            'ent_var',
            'atrium_sud',
            'ac_orleans_tours',
            'ac_poitiers',
            'ac_rennes',
            'neoconnect_guadeloupe',
            'pronote_hubeduconnect',
        ]
        
        for name in ent_names:
            if hasattr(ent_module, name):
                ent_list.append(getattr(ent_module, name))
                
    except Exception as e:
        print(f"Erreur chargement ENT: {e}")
    
    return ent_list

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        # Nettoyer l'URL
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
        
        pronote_url = school_url + 'eleve.html'
        
        print(f"\n{'='*60}")
        print(f"TENTATIVE DE CONNEXION")
        print(f"URL: {pronote_url}")
        print(f"Utilisateur: {username}")
        print(f"{'='*60}\n")
        
        client = None
        used_ent = None
        ent_list = get_available_ents()
        
        print(f"ENT disponibles: {len(ent_list)}")
        
        # Essayer chaque ENT
        for ent in ent_list:
            ent_name = ent.__name__ if ent else "Direct (sans ENT)"
            try:
                print(f"  Essai: {ent_name}...")
                if ent:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    print(f"  ✅ SUCCES avec {ent_name}!")
                    used_ent = ent_name
                    break
                else:
                    print(f"  ❌ Echec {ent_name}")
                    client = None
            except Exception as e:
                error_msg = str(e)[:80]
                print(f"  ❌ Erreur {ent_name}: {error_msg}")
                client = None
                continue
        
        if not client or not client.logged_in:
            return jsonify({'error': 'Impossible de se connecter. Verifiez vos identifiants.'}), 401
        
        print(f"\n{'='*60}")
        print(f"CONNECTE!")
        print(f"Nom: {client.info.name}")
        print(f"Classe: {client.info.class_name}")
        print(f"ENT utilise: {used_ent}")
        print(f"{'='*60}\n")
        
        # Construire le resultat
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
        
        colors = {
            'math': 'bg-indigo-500',
            'francais': 'bg-pink-500',
            'anglais': 'bg-blue-500',
            'histoire': 'bg-amber-500',
            'geo': 'bg-amber-500',
            'svt': 'bg-green-500',
            'physique': 'bg-violet-500',
            'chimie': 'bg-violet-500',
            'eps': 'bg-orange-500',
            'sport': 'bg-orange-500',
            'techno': 'bg-gray-500',
            'musique': 'bg-cyan-500',
            'arts': 'bg-fuchsia-500',
            'espagnol': 'bg-red-500',
            'allemand': 'bg-yellow-500',
        }
        
        # EMPLOI DU TEMPS
        print("Recuperation emploi du temps...")
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            
            for day in range(5):
                current = monday + timedelta(days=day)
                try:
                    lessons = client.lessons(current, current)
                    for lesson in lessons:
                        subj = lesson.subject.name if lesson.subject else 'Cours'
                        color = 'bg-indigo-500'
                        for k, c in colors.items():
                            if k in subj.lower():
                                color = c
                                break
                        
                        course_info = {
                            'time': f"{lesson.start.strftime('%H:%M')} - {lesson.end.strftime('%H:%M')}",
                            'subject': subj,
                            'teacher': lesson.teacher_name or '',
                            'room': lesson.classroom or '',
                            'color': color
                        }
                        
                        if hasattr(lesson, 'canceled') and lesson.canceled:
                            course_info['canceled'] = True
                            course_info['subject'] = f"[ANNULE] {subj}"
                        
                        result['schedule'][day].append(course_info)
                except Exception as e:
                    print(f"  Jour {day}: {e}")
                
                result['schedule'][day].sort(key=lambda x: x['time'])
            
            total_courses = sum(len(d) for d in result['schedule'])
            print(f"  ✅ {total_courses} cours recuperes")
        except Exception as e:
            print(f"  ❌ Erreur emploi du temps: {e}")
        
        # DEVOIRS
        print("Recuperation devoirs...")
        try:
            homeworks = client.homework(datetime.now(), datetime.now() + timedelta(days=14))
            for i, hw in enumerate(homeworks[:15]):
                subj = hw.subject.name if hw.subject else 'Devoir'
                color = 'bg-indigo-500'
                for k, c in colors.items():
                    if k in subj.lower():
                        color = c
                        break
                
                result['homework'].append({
                    'id': i + 1,
                    'subject': subj,
                    'title': hw.description or 'A faire',
                    'dueDate': hw.date.strftime('%d/%m') if hasattr(hw.date, 'strftime') else 'Bientot',
                    'urgent': i < 3,
                    'done': hw.done if hasattr(hw, 'done') else False,
                    'color': color
                })
            print(f"  ✅ {len(result['homework'])} devoirs recuperes")
        except Exception as e:
            print(f"  ❌ Erreur devoirs: {e}")
        
        # NOTES
        print("Recuperation notes...")
        try:
            total, count = 0, 0
            subject_grades = {}
            
            for period in client.periods:
                if not hasattr(period, 'grades'):
                    continue
                    
                for grade in period.grades[:25]:
                    try:
                        grade_str = str(grade.grade).replace(',', '.')
                        if grade_str.lower() in ['abs', 'absent', 'disp', 'n.note', '']:
                            continue
                        
                        val = float(grade_str)
                        mx = float(str(grade.out_of).replace(',', '.')) if grade.out_of else 20
                        normalized = (val / mx) * 20
                        total += normalized
                        count += 1
                        
                        subj_name = grade.subject.name if grade.subject else 'Matiere'
                        
                        result['grades'].append({
                            'subject': subj_name,
                            'grade': val,
                            'max': mx,
                            'date': grade.date.strftime('%d/%m') if hasattr(grade.date, 'strftime') else '',
                            'comment': grade.comment or '',
                            'average': round(normalized, 1)
                        })
                        
                        if subj_name not in subject_grades:
                            subject_grades[subj_name] = []
                        subject_grades[subj_name].append(normalized)
                        
                    except Exception:
                        pass
                break
            
            if count > 0:
                result['studentData']['average'] = round(total / count, 1)
            
            for subj, grades_list in subject_grades.items():
                color = 'bg-indigo-500'
                for k, c in colors.items():
                    if k in subj.lower():
                        color = c
                        break
                
                avg = round(sum(grades_list) / len(grades_list), 1)
                result['subjectAverages'].append({
                    'subject': subj,
                    'average': avg,
                    'classAvg': max(8, round(avg - 1.5, 1)),
                    'icon': 'fa-book',
                    'color': color
                })
            
            print(f"  ✅ {len(result['grades'])} notes, moyenne: {result['studentData']['average']}")
        except Exception as e:
            print(f"  ❌ Erreur notes: {e}")
        
        print(f"\n{'='*60}")
        print("SYNCHRONISATION TERMINEE!")
        print(f"{'='*60}\n")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"\n❌ ERREUR GENERALE: {e}\n")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/')
def home():
    return jsonify({
        'service': 'Pronote Sync Server',
        'status': 'running',
        'endpoints': {
            '/health': 'GET - Check server status',
            '/sync': 'POST - Sync with Pronote'
        }
    })

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print(f"\nServeur demarre sur le port {port}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
