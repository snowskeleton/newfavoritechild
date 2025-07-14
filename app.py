import string
from random import choices
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv
import jwt

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Database setup
DATABASE = os.environ.get('DATABASE_PATH', 'newfavoritechild.db')

# JWT utils
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret')
JWT_ALGO = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

def init_db():
    """Initialize the database with required tables."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            is_admin BOOLEAN DEFAULT FALSE,
            is_editor BOOLEAN DEFAULT FALSE,
            is_subscribed BOOLEAN DEFAULT TRUE,
            magic_token TEXT,
            token_expires DATETIME
        )
    ''')
    
    # Create favorite_child table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorite_child (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            reason TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            set_by TEXT,
            FOREIGN KEY(family_id) REFERENCES families(id),
            FOREIGN KEY(set_by) REFERENCES users(email)
        )
    ''')

    # Create families table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            owner_email TEXT NOT NULL,
            FOREIGN KEY(owner_email) REFERENCES users(email)
        )
    ''')

    # Create family_members table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_members (
            user_email TEXT NOT NULL,
            family_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ("owner", "admin", "member")),
            PRIMARY KEY (user_email, family_id),
            FOREIGN KEY(user_email) REFERENCES users(email),
            FOREIGN KEY(family_id) REFERENCES families(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def send_magic_link(email):
    """Send magic link to user's email."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)  # 1 hour expiry
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user exists first
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    existing_user = cursor.fetchone()
    
    if existing_user:
        # Update existing user - preserve their permissions
        cursor.execute('''
            UPDATE users 
            SET magic_token = ?, token_expires = ?
            WHERE email = ?
        ''', (token, expires, email))
    else:
        # Create new user with default permissions
        cursor.execute('''
            INSERT INTO users (email, magic_token, token_expires, is_subscribed)
            VALUES (?, ?, ?, TRUE)
        ''', (email, token, expires))
    
    conn.commit()
    conn.close()
    
    # Send email with magic link
    magic_url = f"{request.host_url.rstrip('/')}{url_for('magic_login', token=token)}"
    
    subject = "Login to New Favorite Child"
    body = f"""
    Click this link to log in to New Favorite Child:
    
    {magic_url}
    
    This link will expire in 1 hour.
    
    If you didn't request this, you can safely ignore this email.
    """
    
    send_email(email, subject, body)

def send_email(to_email, subject, body):
    """Send email using Fastmail SMTP."""
    # Email configuration - set these as environment variables
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.fastmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_username = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    from_email = os.environ.get('FROM_EMAIL', smtp_username)
    
    if not all([smtp_username, smtp_password]):
        print(f"Email not sent - missing SMTP credentials. Would send to {to_email}: {subject}")
        return
    
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

def send_favorite_child_notification(child_name, reason):
    """Send notification to all subscribed users about new favorite child."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT email FROM users WHERE is_subscribed = TRUE')
    subscribers = cursor.fetchall()
    conn.close()
    
    for subscriber in subscribers:
        email = subscriber['email']
        subject = f"New Favorite Child: {child_name}"
        
        # Create unsubscribe link
        unsubscribe_url = f"{request.host_url.rstrip('/')}{url_for('unsubscribe', email=email)}"
        
        body = f"""
        Breaking News! A new favorite child has been crowned!
        
        Name: {child_name}
        Reason: {reason}
        
        This announcement was made at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.
        
        ---
        To unsubscribe from these notifications, click here: {unsubscribe_url}
        """
        
        # Send email in background thread
        threading.Thread(target=send_email, args=(email, subject, body)).start()

@app.route('/')
def home():
    """Home page showing current favorite child and subscribe form."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current favorite child
    cursor.execute('SELECT * FROM favorite_child ORDER BY timestamp DESC LIMIT 1')
    current_favorite = cursor.fetchone()
    
    # Get recent history (last 5)
    cursor.execute('''
        SELECT * FROM favorite_child 
        ORDER BY timestamp DESC 
        LIMIT 5
    ''')
    recent_history = cursor.fetchall()
    
    conn.close()
    
    return render_template('home.html', current_favorite=current_favorite, recent_history=recent_history)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    """Add email to subscription list."""
    email = request.form.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('home'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user already exists
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    existing_user = cursor.fetchone()
    
    if existing_user:
        if existing_user['is_subscribed']:
            flash('You are already subscribed!', 'info')
        else:
            # Resubscribe
            cursor.execute('UPDATE users SET is_subscribed = TRUE WHERE email = ?', (email,))
            conn.commit()
            flash('Welcome back! You have been resubscribed.', 'success')
    else:
        # New user
        cursor.execute('''
            INSERT INTO users (email, is_subscribed)
            VALUES (?, TRUE)
        ''', (email,))
        conn.commit()
        flash('Successfully subscribed! You will receive notifications about new favorite children.', 'success')
    
    conn.close()
    return redirect(url_for('home'))

@app.route('/login')
def login():
    """Show login page."""
    return render_template('login.html')

@app.route('/request_login', methods=['POST'])
def request_login():
    """Request magic link for login."""
    email = request.form.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('login'))
    
    print(f"🔐 Requesting magic link for: {email}")
    send_magic_link(email)
    flash('Check your email for a login link!', 'success')
    return redirect(url_for('login'))

@app.route('/magic_login/<token>')
def magic_login(token):
    """Handle magic link login."""
    print(f"🔗 Attempting magic login with token: {token[:10]}...")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Use current datetime for comparison
    now = datetime.now()
    
    cursor.execute('''
        SELECT * FROM users 
        WHERE magic_token = ? AND token_expires > ?
    ''', (token, now))
    user = cursor.fetchone()
    
    if user:
        print(f"✅ Valid token found for user: {user['email']}")
        # Clear the token
        cursor.execute('''
            UPDATE users 
            SET magic_token = NULL, token_expires = NULL 
            WHERE email = ?
        ''', (user['email'],))
        conn.commit()
        
        session['user_email'] = user['email']
        session['is_admin'] = user['is_admin']
        session['is_editor'] = user['is_editor']
        
        flash(f'Welcome back, {user["email"]}!', 'success')
        conn.close()
        return redirect(url_for('home'))
    else:
        print(f"❌ Invalid or expired token: {token[:10]}...")
        # Let's check what's in the database for debugging
        cursor.execute('SELECT email, magic_token, token_expires FROM users WHERE magic_token IS NOT NULL')
        tokens = cursor.fetchall()
        print(f"🔍 Current tokens in DB: {len(tokens)}")
        for t in tokens:
            print(f"   {t['email']}: {t['magic_token'][:10]}... expires {t['token_expires']}")
        
        conn.close()
        flash('Invalid or expired login link.', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    """Log out user."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

@app.route('/admin')
def admin():
    """Admin panel for setting favorite child and managing users."""
    if not session.get('user_email'):
        flash('Please log in to access the admin panel.', 'error')
        return redirect(url_for('login'))
    
    if not ((session.get('is_admin') or session.get('is_editor'))):
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('home'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all users
    cursor.execute('SELECT * FROM users ORDER BY email')
    users = cursor.fetchall()
    
    # Get current favorite child
    cursor.execute('SELECT * FROM favorite_child ORDER BY timestamp DESC LIMIT 1')
    current_favorite = cursor.fetchone()
    
    conn.close()
    
    return render_template('admin.html', users=users, current_favorite=current_favorite)

@app.route('/set_favorite', methods=['POST'])
def set_favorite():
    """Set new favorite child."""
    if not session.get('user_email'):
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))
    
    if not (session.get('is_admin') or session.get('is_editor')):
        flash('You do not have permission to set the favorite child.', 'error')
        return redirect(url_for('home'))
    
    child_name = request.form.get('child_name', '').strip()
    reason = request.form.get('reason', '').strip()
    
    if not child_name or not reason:
        flash('Please provide both a name and reason.', 'error')
        return redirect(url_for('admin'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO favorite_child (name, reason)
        VALUES (?, ?)
    ''', (child_name, reason))
    conn.commit()
    conn.close()
    
    # Send notifications
    send_favorite_child_notification(child_name, reason)
    
    flash(f'{child_name} is now the new favorite child!', 'success')
    return redirect(url_for('admin'))

@app.route('/add_user', methods=['POST'])
def add_user():
    """Add a new user (admin only)."""
    if not session.get('user_email') or not session.get('is_admin'):
        flash('You do not have permission to add users.', 'error')
        return redirect(url_for('admin'))
    
    email = request.form.get('email', '').strip().lower()
    is_admin = 'is_admin' in request.form
    is_editor = 'is_editor' in request.form
    is_subscribed = 'is_subscribed' in request.form
    
    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('admin'))
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO users (email, is_admin, is_editor, is_subscribed)
        VALUES (?, ?, ?, ?)
    ''', (email, is_admin, is_editor, is_subscribed))
    conn.commit()
    conn.close()
    
    flash(f'User {email} has been added/updated.', 'success')
    return redirect(url_for('admin'))

@app.route('/unsubscribe/<email>')
def unsubscribe(email):
    """Unsubscribe user from notifications."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET is_subscribed = FALSE WHERE email = ?', (email,))
    conn.commit()
    conn.close()
    
    return render_template('unsubscribe.html', email=email)

@app.route('/history')
def history():
    """Show complete history of favorite children with stats."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get total count for pagination
    cursor.execute('SELECT COUNT(*) as total FROM favorite_child')
    total_count = cursor.fetchone()['total']
    
    # Get paginated history
    cursor.execute('''
        SELECT * FROM favorite_child 
        ORDER BY timestamp DESC 
        LIMIT ? OFFSET ?
    ''', (per_page, offset))
    history = cursor.fetchall()
    
    # Calculate fun stats
    cursor.execute('''
        SELECT 
            name,
            COUNT(*) as times_crowned,
            MIN(timestamp) as first_crowned,
            MAX(timestamp) as last_crowned,
            GROUP_CONCAT(reason, '|') as all_reasons
        FROM favorite_child 
        GROUP BY name 
        ORDER BY times_crowned DESC, last_crowned DESC
    ''')
    stats = cursor.fetchall()
    
    # Calculate total days as favorite (simplified - just count entries for now)
    cursor.execute('''
        SELECT 
            name,
            COUNT(*) as total_entries,
            (SELECT COUNT(*) FROM favorite_child) as total_crownings
        FROM favorite_child 
        GROUP BY name
    ''')
    days_stats = cursor.fetchall()
    
    # Get some fun facts
    cursor.execute('''
        SELECT 
            (SELECT COUNT(DISTINCT name) FROM favorite_child) as unique_favorites,
            (SELECT COUNT(*) FROM favorite_child) as total_crownings,
            (SELECT name FROM favorite_child ORDER BY timestamp ASC LIMIT 1) as first_ever,
            (SELECT name FROM favorite_child ORDER BY timestamp DESC LIMIT 1) as current_favorite
    ''')
    fun_facts = cursor.fetchone()
    
    conn.close()
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_prev = page > 1
    has_next = page < total_pages
    
    return render_template('history.html', 
                         history=history, 
                         stats=stats,
                         days_stats=days_stats,
                         fun_facts=fun_facts,
                         page=page,
                         total_pages=total_pages,
                         has_prev=has_prev,
                         has_next=has_next,
                         total_count=total_count)

@app.route('/healthz')
def healthcheck():
    """Health check endpoint."""
    try:
        # Test database connection
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'message': 'New Favorite Child is running smoothly!'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 500

# JWT utils


def create_access_token(email):
    payload = {
        'sub': email,
        'exp': datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_refresh_token(email):
    payload = {
        'sub': email,
        'exp': datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload['sub']
    except Exception:
        return None

# AUTH ENDPOINTS


@app.route('/api/auth/request_link', methods=['POST'])
def api_request_link():
    email = request.json.get('email', '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'error': 'Invalid email'}), 400
    # Generate token for confirmation
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    existing_user = cursor.fetchone()
    if existing_user:
        cursor.execute(
            'UPDATE users SET magic_token = ?, token_expires = ? WHERE email = ?', (token, expires, email))
    else:
        cursor.execute(
            'INSERT INTO users (email, magic_token, token_expires, is_subscribed) VALUES (?, ?, ?, TRUE)', (email, token, expires))
    conn.commit()
    conn.close()
    # Deep link for app
    magic_url = f"newfavoritechild://confirm?token={token}"
    subject = "Login to New Favorite Child"
    body = f"Click this link to log in: {magic_url}\nThis link will expire in 1 hour."
    send_email(email, subject, body)
    return jsonify({'message': 'Check your email for a login link.'})


@app.route('/api/auth/confirm', methods=['POST'])
def api_confirm():
    token = request.json.get('token')
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute(
        'SELECT * FROM users WHERE magic_token = ? AND token_expires > ?', (token, now))
    user = cursor.fetchone()
    if user:
        cursor.execute(
            'UPDATE users SET magic_token = NULL, token_expires = NULL WHERE email = ?', (user['email'],))
        conn.commit()
        access_token = create_access_token(user['email'])
        refresh_token = create_refresh_token(user['email'])
        conn.close()
        return jsonify({'access_token': access_token, 'refresh_token': refresh_token, 'email': user['email']})
    else:
        conn.close()
        return jsonify({'error': 'Invalid or expired token'}), 400


@app.route('/api/auth/refresh', methods=['POST'])
def api_refresh():
    refresh_token = request.json.get('refresh_token')
    email = verify_token(refresh_token)
    if not email:
        return jsonify({'error': 'Invalid refresh token'}), 401
    access_token = create_access_token(email)
    return jsonify({'access_token': access_token})


# FAMILY ENDPOINTS


def generate_family_code():
    return ''.join(choices(string.ascii_letters + string.digits, k=6))


@app.route('/api/families', methods=['POST'])
def create_family():
    data = request.json
    name = data.get('name')
    owner_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not owner_email:
        return jsonify({'error': 'Unauthorized'}), 401
    code = generate_family_code()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO families (name, code, owner_email) VALUES (?, ?, ?)', (name, code, owner_email))
    family_id = cursor.lastrowid
    cursor.execute('INSERT INTO family_members (user_email, family_id, role) VALUES (?, ?, ?)',
                   (owner_email, family_id, 'owner'))
    conn.commit()
    conn.close()
    return jsonify({'id': family_id, 'name': name, 'code': code})


@app.route('/api/families/join', methods=['POST'])
def join_family():
    data = request.json
    code = data.get('code')
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM families WHERE code = ?', (code,))
    family = cursor.fetchone()
    if not family:
        conn.close()
        return jsonify({'error': 'Invalid code'}), 404
    cursor.execute('INSERT OR IGNORE INTO family_members (user_email, family_id, role) VALUES (?, ?, ?)',
                   (user_email, family['id'], 'member'))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Joined family'})


@app.route('/api/families', methods=['GET'])
def list_families():
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT f.id, f.name, f.code, fm.role FROM families f JOIN family_members fm ON f.id = fm.family_id WHERE fm.user_email = ?''', (user_email,))
    families = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'families': families})


@app.route('/api/families/<int:family_id>', methods=['GET'])
def family_details(family_id):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM families WHERE id = ?', (family_id,))
    family = cursor.fetchone()
    if not family:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    cursor.execute(
        'SELECT user_email, role FROM family_members WHERE family_id = ?', (family_id,))
    members = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        'SELECT * FROM favorite_child WHERE family_id = ? ORDER BY timestamp DESC LIMIT 1', (family_id,))
    current_favorite = cursor.fetchone()
    conn.close()
    return jsonify({'family': dict(family), 'members': members, 'current_favorite': dict(current_favorite) if current_favorite else None})


@app.route('/api/families/<int:family_id>/favorite', methods=['POST'])
def set_favorite_child(family_id):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT role FROM family_members WHERE user_email = ? AND family_id = ?', (user_email, family_id))
    role = cursor.fetchone()
    if not role or role['role'] not in ('owner', 'admin'):
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    name = data.get('name')
    reason = data.get('reason')
    cursor.execute('INSERT INTO favorite_child (family_id, name, reason, set_by) VALUES (?, ?, ?, ?)',
                   (family_id, name, reason, user_email))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Favorite child set'})


@app.route('/api/families/<int:family_id>/history', methods=['GET'])
def favorite_history(family_id):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT name, reason, timestamp, set_by FROM favorite_child WHERE family_id = ? ORDER BY timestamp DESC', (family_id,))
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'history': history})


@app.route('/api/families/<int:family_id>/roles', methods=['POST'])
def assign_role(family_id):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cursor = conn.cursor()
    # Only owner can assign roles
    cursor.execute(
        'SELECT role FROM family_members WHERE user_email = ? AND family_id = ?', (user_email, family_id))
    role = cursor.fetchone()
    if not role or role['role'] != 'owner':
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    target_email = data.get('user_email')
    new_role = data.get('role')
    if new_role not in ('admin', 'member'):
        conn.close()
        return jsonify({'error': 'Invalid role'}), 400
    cursor.execute('UPDATE family_members SET role = ? WHERE user_email = ? AND family_id = ?',
                   (new_role, target_email, family_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Role updated'})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5003))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=port) 
