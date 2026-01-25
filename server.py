from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from pronotepy.ent import *
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Liste des ENT a essayer pour Ile-de-France / Seine-et-Marne
ENT_LIST = [
    None,  # Connexion directe (sans ENT)
    ile_de_france,
    ent_creactif,
    paris_classe_numerique,
    monlycee_net,
    ent_somme,
    ent_mayotte,
    laclasse_lyon,
    laclasse_educonnect,
    eclat_bfc,
    occitanie_montpellier,
    cas_agora06,
    ent_94,
    ent_77,
]

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
        
        # Essayer chaque ENT
        for ent in ENT_LIST:
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
                print(f"  ❌ Erreur {ent_name}: {str(e)[:50]}")
                client = None
                continue
        
        if not client or not client.logged_in:
            return jsonify({'error': 'Impossible de se connecter. Verifiez vos identifiants ou contactez le support.'}), 401
        
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
            'français': 'bg-pink-500',
            'anglais': 'bg-blue-500',
            'histoire': 'bg-amber-500',
            'geo': 'bg-amber-500',
            'geographie': 'bg-amber-500',
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
            'latin': 'bg-emerald-500',
            'grec': 'bg-emerald-500'
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
                        
                        # Ajouter info prof absent si applicable
                        if hasattr(lesson, 'canceled') and lesson.canceled:
                            course_info['canceled'] = True
                            course_info['subject'] = f"[ANNULÉ] {subj}"
                        
                        if hasattr(lesson, 'status') and lesson.status:
                            course_info['status'] = lesson.status
                        
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
            
            # Moyennes par matiere
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
        
        # MESSAGES (si disponible)
        print("Recuperation messages...")
        try:
            if hasattr(client, 'discussions'):
                discussions = client.discussions()
                for i, msg in enumerate(discussions[:5]):
                    result['messages'].append({
                        'id': i + 1,
                        'from': str(getattr(msg, 'author', 'Pronote')),
                        'subject': getattr(msg, 'subject', 'Message'),
                        'date': 'Recent',
                        'unread': True,
                        'content': getattr(msg, 'content', '')[:200]
                    })
            print(f"  ✅ {len(result['messages'])} messages")
        except Exception as e:
            print(f"  ⚠️ Messages non disponibles: {e}")
        
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
    print(f"\n{'='*60}")
    print("   SERVEUR PRONOTE DEMARRE!")
    print(f"   Port: {port}")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
