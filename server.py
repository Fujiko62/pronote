from flask import Flask, request, jsonify
from flask_cors import CORS
import pronotepy
from datetime import datetime, timedelta
import functools

app = Flask(__name__)
CORS(app)

def get_available_ents():
    """Priorise les ENT de Seine-et-Marne et Ile-de-France"""
    ent_list = []
    try:
        import pronotepy.ent as ent_module
        
        # Liste prioritaire pour le 77 (Seine-et-Marne)
        priority_names = ['ent_77', 'ile_de_france', 'monlycee_net', 'educonnect']
        
        # Autres ENT au cas ou
        other_names = [
            'paris_classe_numerique', 'ent_somme', 'ac_reunion', 'ac_reims', 
            'occitanie_montpellier', 'cas_agora06', 'eclat_bfc', 'laclasse_lyon', 
            'ent_mayotte', 'ent_hdf', 'ent_var', 'atrium_sud'
        ]
        
        for name in priority_names + other_names:
            if hasattr(ent_module, name):
                ent_list.append(getattr(ent_module, name))
                
        # Ajouter la connexion directe a la fin
        ent_list.append(None)
    except Exception as e:
        print(f"Erreur chargement ENT: {e}")
    return ent_list

def get_ent_display_name(ent):
    if ent is None: return "Direct (sans ENT)"
    if hasattr(ent, '__name__'): return ent.__name__
    if isinstance(ent, functools.partial): return f"Partial({ent.func.__name__})"
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
        
        print(f"\n{'='*60}\nDEBUT SYNCHRO: {username}\n{'='*60}")
        
        client = None
        ent_list = get_available_ents()
        
        for ent in ent_list:
            ent_name = get_ent_display_name(ent)
            try:
                print(f"  Tentative avec: {ent_name}...")
                if ent:
                    client = pronotepy.Client(pronote_url, username=username, password=password, ent=ent)
                else:
                    client = pronotepy.Client(pronote_url, username=username, password=password)
                
                if client.logged_in:
                    print(f"  ✅ CONNECTE via {ent_name}!")
                    break
                client = None
            except Exception as e:
                msg = str(e).lower()
                print(f"  ❌ {ent_name}: {msg[:50]}")
                # Si le message indique clairement un mauvais mot de passe, on arrete de tester les autres
                if "mot de passe" in msg or "password" in msg or "invalid credentials" in msg:
                    return jsonify({'error': 'Identifiants Pronote incorrects.'}), 401
                client = None
        
        if not client or not client.logged_in:
            return jsonify({'error': 'Aucun mode de connexion trouvé. Verifiez vos acces.'}), 401
        
        # On construit les donnees
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
        except: pass

        # Devoirs
        try:
            hws = client.homework(datetime.now(), datetime.now() + timedelta(days=7))
            for hw in hws:
                result['homework'].append({
                    'subject': hw.subject.name if hw.subject else 'Devoir',
                    'title': hw.description,
                    'dueDate': hw.date.strftime('%d/%m'),
                    'done': getattr(hw, 'done', False)
                })
        except: pass

        return jsonify(result)
        
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
