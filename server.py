from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

@app.route('/sync', methods=['POST'])
def sync_pronote():
    try:
        data = request.json
        school_url = data.get('schoolUrl', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([school_url, username, password]):
            return jsonify({'error': 'Parametres manquants'}), 400
        
        print(f"Connexion a Pronote pour {username}...")
        
        if 'eleve.html' in school_url:
            school_url = school_url.split('eleve.html')[0]
        if not school_url.endswith('/'):
            school_url += '/'
            
        client = pronotepy.Client(school_url + 'eleve.html', username=username, password=password)
        
        if not client.logged_in:
            return jsonify({'error': 'Echec de connexion'}), 401
        
        print(f"Connecte: {client.info.name}")
        
        result = {
            'studentData': {'name': client.info.name, 'class': client.info.class_name, 'average': 0, 'rank': 1, 'totalStudents': 30},
            'schedule': [[], [], [], [], []],
            'homework': [],
            'grades': [],
            'subjectAverages': [],
            'messages': []
        }
        
        colors = {'math': 'bg-indigo-500', 'francais': 'bg-pink-500', 'anglais': 'bg-blue-500', 'histoire': 'bg-amber-500', 'svt': 'bg-green-500', 'physique': 'bg-violet-500', 'eps': 'bg-orange-500'}
        
        try:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            for day in range(5):
                current = monday + timedelta(days=day)
                try:
                    for lesson in client.lessons(current, current):
                        subj = lesson.subject.name if lesson.subject else 'Cours'
                        color = 'bg-indigo-500'
                        for k, c in colors.items():
                            if k in subj.lower():
                                color = c
                                break
                        result['schedule'][day].append({'time': f"{lesson.start.strftime('%H:%M')} - {lesson.end.strftime('%H:%M')}", 'subject': subj, 'teacher': lesson.teacher_name or '', 'room': lesson.classroom or '', 'color': color})
                except:
                    pass
                result['schedule'][day].sort(key=lambda x: x['time'])
        except Exception as e:
            print(f"Erreur emploi du temps: {e}")
        
        try:
            for i, hw in enumerate(client.homework(datetime.now(), datetime.now() + timedelta(days=14))[:10]):
                result['homework'].append({'id': i+1, 'subject': hw.subject.name if hw.subject else 'Devoir', 'title': hw.description or 'A faire', 'dueDate': hw.date.strftime('%d/%m') if hasattr(hw.date, 'strftime') else 'Bientot', 'urgent': i < 2, 'done': hw.done, 'color': 'bg-indigo-500'})
        except Exception as e:
            print(f"Erreur devoirs: {e}")
        
        try:
            total, count = 0, 0
            for period in client.periods:
                for grade in period.grades[:15]:
                    try:
                        val = float(str(grade.grade).replace(',', '.'))
                        mx = float(str(grade.out_of).replace(',', '.')) if grade.out_of else 20
                        total += (val / mx) * 20
                        count += 1
                        result['grades'].append({'subject': grade.subject.name if grade.subject else 'Matiere', 'grade': val, 'max': mx, 'date': grade.date.strftime('%d/%m') if hasattr(grade.date, 'strftime') else '', 'comment': grade.comment or '', 'average': val})
                    except:
                        pass
                break
            if count > 0:
                result['studentData']['average'] = round(total / count, 1)
        except Exception as e:
            print(f"Erreur notes: {e}")
        
        print("Donnees recuperees!")
        return jsonify(result)
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("   SERVEUR PRONOTE DEMARRE !")
    print("="*50)
    print("\nAdresse: http://localhost:5000")
    print("\nPour connecter le site, ouvrez la console (F12)")
    print("et tapez:")
    print("localStorage.setItem('PRONOTE_BRIDGE', 'http://localhost:5000')")
    print("\n")
    app.run(host='0.0.0.0', port=5000, debug=True)