import os
import sqlite3
import datetime
from flask import Flask, render_template_string, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'lty-speak-secure-2026')
# SocketIO Setup für Northflank (CORS erlaubt Zugriffe von der Northflank-URL)
socketio = SocketIO(app, cors_allowed_origins="*")

DB_FILE = 'lty_speak.db'

# --- DATENBANK FUNKTIONEN ---
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Tabellen für User, Freunde und Chat-Verlauf
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, nickname TEXT, password TEXT, 
            is_owner INTEGER, prefix TEXT, banner_color TEXT, status_msg TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS friends (
            user1 TEXT, user2 TEXT, PRIMARY KEY(user1, user2))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
            room_id TEXT, sender TEXT, sender_nick TEXT, text TEXT, time TEXT, is_owner INTEGER, prefix TEXT)''')
        
        # Erstelle 9lty als Owner mit deinem Passwort, falls er noch nicht existiert
        owner = conn.execute('SELECT * FROM users WHERE username = ?', ('9lty',)).fetchone()
        if not owner:
            conn.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('9lty', '9lty', generate_password_hash('GLh16.08.2011'), 1, 'OWNER', '#ff0000', 'System Administrator'))
        conn.commit()

init_db()

# ==============================================================================
# UI DESIGN (HTML & CSS direkt im Code)
# ==============================================================================
CSS = """
<style>
    :root { --bg-guilds: #1e1f22; --bg-sidebar: #2b2d31; --bg-chat: #313338; --text-normal: #dbdee1; --text-muted: #949ba4; --brand-yellow: #ffdd00; --owner-red: #ff4444; }
    body, html { margin: 0; padding: 0; height: 100%; font-family: sans-serif; background: var(--bg-guilds); color: var(--text-normal); overflow: hidden; }
    .app { display: flex; height: 100vh; }
    .guilds { width: 72px; background: var(--bg-guilds); display: flex; flex-direction: column; align-items: center; padding-top: 12px; gap: 8px; }
    .g-icon { width: 48px; height: 48px; background: #313338; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.2s; font-weight: bold; }
    .g-icon:hover, .active { border-radius: 16px; background: var(--brand-yellow); color: black; }
    .sidebar { width: 240px; background: var(--bg-sidebar); display: flex; flex-direction: column; }
    .scroller { flex-grow: 1; padding: 8px; overflow-y: auto; }
    .dm-link { display: flex; align-items: center; gap: 12px; padding: 8px; border-radius: 4px; text-decoration: none; color: var(--text-muted); }
    .dm-link:hover, .sel { background: rgba(78, 80, 88, 0.3); color: white; }
    .user-panel { background: #232428; padding: 8px; display: flex; align-items: center; gap: 8px; }
    .chat { flex-grow: 1; background: var(--bg-chat); display: flex; flex-direction: column; }
    .chat-header { height: 48px; padding: 0 16px; display: flex; align-items: center; border-bottom: 1px solid #1e1f22; font-weight: bold; }
    .msgs { flex-grow: 1; overflow-y: auto; padding: 16px; }
    .msg { display: flex; gap: 16px; margin-bottom: 16px; }
    .author { font-weight: bold; color: white; }
    .is-owner { color: var(--owner-red) !important; }
    .prefix { background: #444; color: white; font-size: 10px; padding: 2px 4px; border-radius: 3px; margin-right: 4px; }
    .p-owner { background: var(--owner-red); }
    .input-area { padding: 0 16px 24px 16px; }
    .input-box { background: #383a40; border-radius: 8px; padding: 10px; }
    .input-box input { background: transparent; border: none; color: white; width: 100%; outline: none; }
    .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:99; align-items:center; justify-content:center; }
    .modal-content { background: var(--bg-chat); padding: 24px; border-radius: 8px; width: 400px; border: 1px solid #444; }
</style>
"""

LAYOUT = CSS + """
<div class="app">
    <div class="guilds">
        <div class="g-icon active" onclick="location.href='/'">L</div>
        <div class="g-icon" onclick="document.getElementById('add-m').style.display='flex'">+</div>
    </div>
    <div class="sidebar">
        <div class="scroller">
            <div style="font-size:12px; color:var(--text-muted); font-weight:bold; padding:10px;">DIRECT MESSAGES</div>
            {% for f in friends %}
            <a href="/chat/{{ f }}" class="dm-link {{ 'sel' if p_name == f }}">
                <div style="width:32px; height:32px; border-radius:50%; background:#444; display:flex; align-items:center; justify-content:center;">{{ f[0].upper() }}</div>
                {{ f }}
            </a>
            {% endfor %}
        </div>
        <div class="user-panel">
            <div style="width:32px; height:32px; border-radius:50%; background:var(--brand-yellow); color:black; display:flex; align-items:center; justify-content:center; font-weight:bold;">{{ user.nickname[0].upper() }}</div>
            <div style="flex-grow:1; font-size:13px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{{ user.nickname }}</div>
            <div style="cursor:pointer;" onclick="document.getElementById('set-m').style.display='flex'">⚙️</div>
        </div>
    </div>
    <div class="chat">
        <div class="chat-header">@ <span class="{{ 'is-owner' if partner and partner.is_owner }}">{{ partner.nickname if partner else 'Welcome' }}</span></div>
        <div class="msgs" id="m-box">
            {% if partner %}
                {% for m in history %}
                <div class="msg">
                    <div style="width:40px; height:40px; background:#444; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center;">{{ m.sender_nick[0].upper() }}</div>
                    <div>
                        <div>
                            {% if m.prefix %}<span class="prefix {{ 'p-owner' if m.is_owner }}">{{ m.prefix }}</span>{% endif %}
                            <span class="author {{ 'is-owner' if m.is_owner }}">{{ m.sender_nick }}</span>
                            <span style="font-size:12px; color:var(--text-muted); margin-left:8px;">{{ m.time }}</span>
                        </div>
                        <div style="margin-top:2px;">{{ m.text }}</div>
                    </div>
                </div>
                {% endfor %}
            {% endif %}
        </div>
        {% if partner %}
        <div class="input-area"><div class="input-box"><input id="ci" placeholder="Message @{{ partner.nickname }}" onkeypress="send(event)"></div></div>
        {% endif %}
    </div>
</div>

<div id="add-m" class="modal"><div class="modal-content">
    <h3>Add Friend</h3>
    <form action="/add_friend" method="POST"><input name="fu" placeholder="Username" style="width:100%; padding:10px; background:#1e1f22; border:none; color:white; margin-bottom:10px;">
    <button style="width:100%; background:var(--brand-yellow); border:none; padding:10px; font-weight:bold;">Add Friend</button></form>
    <button onclick="document.getElementById('add-m').style.display='none'" style="width:100%; background:none; border:none; color:white; margin-top:10px;">Cancel</button>
</div></div>

<div id="set-m" class="modal"><div class="modal-content" style="max-height:80vh; overflow-y:auto;">
    <h3 style="color:var(--brand-yellow);">Settings</h3>
    <form action="/update" method="POST">
        <label style="font-size:12px;">NICKNAME</label><input name="n" value="{{ user.nickname }}" style="width:100%; padding:10px; background:#1e1f22; border:none; color:white; margin-bottom:10px;">
        <button style="width:100%; background:var(--brand-yellow); border:none; padding:10px; font-weight:bold;">Save Nickname</button>
    </form>
    
    {% if user.is_owner %}
    <div style="border-top:1px solid #444; margin-top:20px; padding-top:10px;">
        <h4 style="color:var(--owner-red);">Admin: User Prefixes</h4>
        <form action="/admin_prefix" method="POST">
            {% for u in all_users %}
            <div style="display:flex; justify-content:space-between; margin-bottom:5px; align-items:center;">
                <span style="font-size:13px;">{{ u.username }}</span>
                <input name="pre_{{ u.username }}" value="{{ u.prefix or '' }}" placeholder="z.B. VIP" style="background:#1e1f22; border:none; color:white; padding:4px 8px; width:100px; border-radius:3px;">
            </div>
            {% endfor %}
            <button style="width:100%; background:var(--owner-red); color:white; border:none; padding:10px; font-weight:bold; margin-top:10px;">Update All Prefixes</button>
        </form>
    </div>
    {% endif %}
    <button onclick="document.getElementById('set-m').style.display='none'" style="width:100%; background:none; border:none; color:white; margin-top:10px; cursor:pointer;">Close</button>
    <div style="margin-top:15px; text-align:center;"><a href="/logout" style="color:#ff4444; text-decoration:none; font-size:12px;">Logout</a></div>
</div></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/socketio/4.0.1/socketio.js"></script>
<script>
    const socket = io();
    const box = document.getElementById('m-box');
    if(box) box.scrollTop = box.scrollHeight;

    function send(e) {
        if(e.key === 'Enter') {
            const i = document.getElementById('ci');
            if(!i.value) return;
            socket.emit('msg', { t: "{{ p_name }}", m: i.value });
            i.value = '';
        }
    }

    socket.on('rec', (d) => {
        const div = document.createElement('div'); div.className = 'msg';
        div.innerHTML = `
            <div style="width:40px; height:40px; background:#444; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center;">${d.sender_nick[0].toUpperCase()}</div>
            <div>
                <div>
                    ${d.prefix ? `<span class="prefix ${d.is_owner?'p-owner':''}">${d.prefix}</span>` : ''}
                    <span class="author ${d.is_owner?'is-owner':''}">${d.sender_nick}</span>
                    <span style="font-size:12px; color:var(--text-muted); margin-left:8px;">${d.time}</span>
                </div>
                <div style="margin-top:2px;">${d.text}</div>
            </div>`;
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
    });
</script>
"""

# ==============================================================================
# LOGIK / ROUTEN
# ==============================================================================

@app.route('/')
def index():
    if 'u' not in session: return redirect('/login')
    db = get_db()
    u = db.execute('SELECT * FROM users WHERE username = ?', (session['u'],)).fetchone()
    friends = [f['user2'] for f in db.execute('SELECT user2 FROM friends WHERE user1 = ?', (session['u'],)).fetchall()]
    all_u = db.execute('SELECT username, prefix FROM users').fetchall() if u['is_owner'] else []
    return render_template_string(LAYOUT, user=u, friends=friends, partner=None, p_name=None, all_users=all_u)

@app.route('/chat/<name>')
def chat(name):
    if 'u' not in session: return redirect('/login')
    db = get_db()
    u = db.execute('SELECT * FROM users WHERE username = ?', (session['u'],)).fetchone()
    p = db.execute('SELECT * FROM users WHERE username = ?', (name,)).fetchone()
    if not p: return redirect('/')
    friends = [f['user2'] for f in db.execute('SELECT user2 FROM friends WHERE user1 = ?', (session['u'],)).fetchall()]
    rid = "_".join(sorted([session['u'], name]))
    history = db.execute('SELECT * FROM messages WHERE room_id = ?', (rid,)).fetchall()
    all_u = db.execute('SELECT username, prefix FROM users').fetchall() if u['is_owner'] else []
    return render_template_string(LAYOUT, user=u, friends=friends, partner=p, p_name=name, history=history, all_users=all_u)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        u = db.execute('SELECT * FROM users WHERE username = ?', (request.form['u'].lower().strip(),)).fetchone()
        if u and check_password_hash(u['password'], request.form['p']):
            session['u'] = u['username']
            return redirect('/')
    return '<h2>Lty Speak - Login</h2><form method="POST"><input name="u" placeholder="Username"><input name="p" type="password" placeholder="Passwort"><button>Login</button></form><br><a href="/reg">Registrieren</a>'

@app.route('/reg', methods=['GET', 'POST'])
def reg():
    if request.method == 'POST':
        db = get_db()
        try:
            db.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)',
                (request.form['u'].lower().strip(), request.form['n'], generate_password_hash(request.form['p']), 0, '', '#4e5058', 'Hi!'))
            db.commit()
            return redirect('/login')
        except: return "Fehler: User existiert bereits."
    return '<h2>Lty Speak - Account erstellen</h2><form method="POST"><input name="u" placeholder="Login-Name"><input name="n" placeholder="Anzeigename (Nick)"><input name="p" type="password" placeholder="Passwort"><button>Registrieren</button></form>'

@app.route('/update', methods=['POST'])
def update():
    if 'u' not in session: return redirect('/login')
    db = get_db()
    db.execute('UPDATE users SET nickname = ? WHERE username = ?', (request.form['n'], session['u']))
    db.commit()
    return redirect('/')

@app.route('/admin_prefix', methods=['POST'])
def admin_prefix():
    if 'u' not in session: return redirect('/login')
    db = get_db()
    u = db.execute('SELECT is_owner FROM users WHERE username = ?', (session['u'],)).fetchone()
    if u and u['is_owner']:
        for key, val in request.form.items():
            if key.startswith('pre_'):
                target_user = key.replace('pre_', '')
                db.execute('UPDATE users SET prefix = ? WHERE username = ?', (val, target_user))
        db.commit()
    return redirect('/')

@app.route('/add_friend', methods=['POST'])
def add_friend():
    if 'u' not in session: return redirect('/login')
    db = get_db()
    f = request.form['fu'].lower().strip()
    if db.execute('SELECT * FROM users WHERE username = ?', (f,)).fetchone():
        db.execute('INSERT OR IGNORE INTO friends VALUES (?, ?)', (session['u'], f))
        db.execute('INSERT OR IGNORE INTO friends VALUES (?, ?)', (f, session['u']))
        db.commit()
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@socketio.on('msg')
def handle_msg(d):
    if 'u' not in session: return
    db = get_db()
    u = db.execute('SELECT * FROM users WHERE username = ?', (session['u'],)).fetchone()
    t = datetime.datetime.now().strftime("%H:%M")
    rid = "_".join(sorted([session['u'], d['t']]))
    
    msg_data = {
        'sender_nick': u['nickname'], 
        'text': d['m'], 
        'time': t, 
        'is_owner': u['is_owner'], 
        'prefix': u['prefix']
    }
    
    db.execute('INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)',
               (rid, session['u'], u['nickname'], d['m'], t, u['is_owner'], u['prefix']))
    db.commit()
    emit('rec', msg_data, room=session['u'])
    emit('rec', msg_data, room=d['t'])

@socketio.on('connect')
def cn():
    if 'u' in session: join_room(session['u'])

if __name__ == '__main__':
    # Port dynamisch für Hosting-Anbieter (Northflank/Railway/Render) setzen
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
