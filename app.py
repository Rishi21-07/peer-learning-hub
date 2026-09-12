import os
import sqlite3
import datetime
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='.', static_url_path='')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_FILE = 'database.db'

class CursorWrapper:
    def __init__(self, cursor, is_pg):
        self.cursor = cursor
        self.is_pg = is_pg
        self.lastrowid = None

    def execute(self, sql, params=()):
        if self.is_pg:
            # Dialect adjustments
            sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            sql = sql.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
            sql = sql.replace('?', '%s')
            
            is_insert_users = sql.strip().upper().startswith('INSERT INTO USERS')
            if is_insert_users:
                sql += ' RETURNING id'
                
            self.cursor.execute(sql, params)
            if is_insert_users:
                self.lastrowid = self.cursor.fetchone()['id']
        else:
            self.cursor.execute(sql, params)
            self.lastrowid = getattr(self.cursor, 'lastrowid', None)
        return self

    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()

class DBWrapper:
    def __init__(self, conn, is_pg):
        self.conn = conn
        self.is_pg = is_pg
    def cursor(self): return CursorWrapper(self.conn.cursor(), self.is_pg)
    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        # Fix Render postgres URL if needed (postgres:// -> postgresql://)
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return DBWrapper(conn, True)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return DBWrapper(conn, False)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    college TEXT,
                    phone TEXT,
                    department TEXT,
                    year TEXT,
                    interests TEXT,
                    points INTEGER DEFAULT 50
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    subject TEXT,
                    title TEXT,
                    description TEXT,
                    filename TEXT,
                    date_uploaded TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS doubts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    title TEXT,
                    answers_count INTEGER DEFAULT 0,
                    date_posted TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doubt_id INTEGER,
                    user_id INTEGER,
                    user_name TEXT,
                    text TEXT,
                    upvotes INTEGER DEFAULT 0,
                    downvotes INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    act_type TEXT,
                    subject TEXT,
                    details TEXT,
                    time_info TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS private_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_user_id INTEGER,
                    message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY, user_id INTEGER, user_name TEXT, text TEXT, date_sent TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if email already exists
    c.execute("SELECT * FROM users WHERE email=?", (data.get('email'),))
    if c.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Email already exists! Please log in."}), 400
        
    c.execute("INSERT INTO users (name, email, password, college, phone, department, year, interests) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (data.get('name'), data.get('email'), data.get('password'), data.get('college'), '', data.get('department', 'IT Department'), data.get('year', '3rd Year'), data.get('interests', 'OS, DBMS')))
    conn.commit()
    user_id = c.lastrowid
    conn.close()
    return jsonify({"success": True, "message": "User created!", "user": {"id": user_id, "name": data.get('name'), "email": data.get('email')}})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (data.get('email'),))
    user_exists = c.fetchone()
    if not user_exists:
        conn.close()
        return jsonify({"success": False, "message": "Account not found, please create an account first"}), 404
        
    c.execute("SELECT * FROM users WHERE email=? AND password=?", (data.get('email'), data.get('password')))
    user = c.fetchone()
    conn.close()
    if user:
        return jsonify({"success": True, "user": {"id": user['id'], "name": user['name'], "email": user['email']}})
    return jsonify({"success": False, "message": "Invalid password"}), 401

@app.route('/api/upload', methods=['POST'])
def upload_note():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No selected file"}), 400
    if file:
        filename = secure_filename(file.filename)
        filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        user_id = request.form.get('user_id')
        user_name = request.form.get('user_name')
        subject = request.form.get('subject')
        title = request.form.get('title')
        description = request.form.get('description')
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO notes (user_id, user_name, subject, title, description, filename, date_uploaded) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (user_id, user_name, subject, title, description, filename, datetime.datetime.now().isoformat()))
        # Give user points for uploading
        c.execute("UPDATE users SET points = points + 10 WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Note uploaded successfully!"})

@app.route('/api/notes', methods=['GET'])
def get_notes():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM notes ORDER BY id DESC")
    notes = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(notes)

@app.route('/api/doubts', methods=['GET', 'POST'])
def handle_doubts():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        c.execute("INSERT INTO doubts (user_id, user_name, title, date_posted) VALUES (?, ?, ?, ?)",
                  (data.get('user_id'), data.get('user_name'), data.get('title'), datetime.datetime.now().isoformat()))
        c.execute("UPDATE users SET points = points + 2 WHERE id=?", (data.get('user_id'),))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    else:
        c.execute("SELECT * FROM doubts ORDER BY id DESC")
        doubts = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify(doubts)

@app.route('/api/chat', methods=['GET', 'POST'])
def handle_chat():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        c.execute("INSERT INTO messages (user_id, user_name, text, date_sent) VALUES (?, ?, ?, ?)",
                  (data.get('user_id'), data.get('user_name'), data.get('text'), datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    else:
        c.execute("SELECT * FROM messages ORDER BY id ASC")
        messages = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify(messages)

@app.route('/api/buddies', methods=['GET'])
def get_buddies():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, department, year, interests FROM users WHERE id != ? ORDER BY id DESC", (user_id,))
    buddies = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(buddies)

@app.route('/api/profile', methods=['GET'])
def get_profile():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
        
    c.execute("SELECT COUNT(*) as c FROM resources WHERE uploader_id=?", (user_id,))
    notes_shared = c.fetchone()['c']
    
    c.execute("SELECT COUNT(*) as c FROM answers WHERE user_id=?", (user_id,))
    doubts_answered = c.fetchone()['c']
    
    conn.close()
    
    return jsonify({
        "name": user['name'],
        "email": user['email'],
        "phone": user['phone'],
        "department": user['department'],
        "year": user['year'],
        "interests": user['interests'],
        "points": user['points'],
        "notes_shared": notes_shared,
        "doubts_answered": doubts_answered
    })

@app.route('/api/profile/<int:user_id>', methods=['PUT'])
def update_profile(user_id):
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE users 
        SET name=?, email=?, phone=?, department=?, year=?, interests=?
        WHERE id=?
    """, (data.get('name'), data.get('email'), data.get('phone'), data.get('department'), data.get('year'), data.get('interests'), user_id))
    conn.commit()
    
    c.execute("SELECT id, name, email, phone, college, department, year, interests, points FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({"success": True, "user": dict(row)})
    return jsonify({"success": False, "error": "User not found"}), 404

@app.route('/api/profile/stats', methods=['GET'])
def get_stats():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get user info
    c.execute("SELECT points, department, year FROM users WHERE id=?", (user_id,))
    user = dict(c.fetchone())
    
    # Get notes count
    c.execute("SELECT COUNT(*) as c FROM notes WHERE user_id=?", (user_id,))
    notes_count = c.fetchone()['c']
    
    conn.close()
    return jsonify({
        "notes_shared": notes_count,
        "points": user['points'],
        "helped_peers": notes_count * 2, # Fake stat for demo
        "department": user['department'],
        "year": user['year']
    })

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/doubts/<int:doubt_id>/answers', methods=['GET', 'POST'])
def handle_answers(doubt_id):
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        c.execute("INSERT INTO answers (doubt_id, user_id, user_name, text) VALUES (?, ?, ?, ?)",
                  (doubt_id, data.get('user_id'), data.get('user_name'), data.get('text')))
        c.execute("UPDATE doubts SET answers_count = answers_count + 1 WHERE id = ?", (doubt_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    else:
        c.execute("SELECT * FROM answers WHERE doubt_id=? ORDER BY timestamp ASC", (doubt_id,))
        rows = c.fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

@app.route('/api/answers/<int:answer_id>/vote', methods=['POST'])
def vote_answer(answer_id):
    data = request.json
    vote_type = data.get('vote') # 'up' or 'down'
    conn = get_db_connection()
    c = conn.cursor()
    if vote_type == 'up':
        c.execute("UPDATE answers SET upvotes = upvotes + 1 WHERE id = ?", (answer_id,))
    elif vote_type == 'down':
        c.execute("UPDATE answers SET downvotes = downvotes + 1 WHERE id = ?", (answer_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/express_interest', methods=['POST'])
def express_interest():
    data = request.json
    target_user_id = data.get('target_user_id')
    interested_user_id = data.get('interested_user_id')
    
    conn = get_db_connection()
    c = conn.cursor()
    # Fetch interested user's contact details
    c.execute("SELECT name, email, phone FROM users WHERE id=?", (interested_user_id,))
    user_info = c.fetchone()
    if user_info:
        msg = f"{user_info['name']} is interested in your broadcast! Contact them at: Email: {user_info['email']} | Phone: {user_info['phone'] or 'Not provided'}"
        c.execute("INSERT INTO private_notifications (target_user_id, message) VALUES (?, ?)", (target_user_id, msg))
        conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/notifications/private/<int:id>', methods=['DELETE'])
def delete_private_notification(id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM private_notifications WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/activities', methods=['GET', 'POST'])
def handle_activities():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        c.execute("INSERT INTO activities (user_id, user_name, act_type, subject, details, time_info) VALUES (?, ?, ?, ?, ?, ?)",
                  (data.get('user_id'), data.get('user_name'), data.get('act_type'), data.get('subject'), data.get('details'), data.get('time_info', '')))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    else:
        user_id = request.args.get('user_id')
        c.execute("SELECT * FROM activities ORDER BY timestamp DESC LIMIT 50")
        acts = [dict(r) for r in c.fetchall()]
        if user_id:
            c.execute("SELECT * FROM private_notifications WHERE target_user_id=? ORDER BY timestamp DESC LIMIT 50", (user_id,))
            privates = [dict(r) for r in c.fetchall()]
            for p in privates:
                p['act_type'] = 'private'
                acts.append(p)
            acts.sort(key=lambda x: x['timestamp'], reverse=True)
        conn.close()
        return jsonify(acts)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')
