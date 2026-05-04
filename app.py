import string
from random import choices
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv
import jwt
from models import db, User
from typing import Optional, Any, cast
import requests

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=365)


@app.before_request
def refresh_session():
    """Make session permanent and refresh expiry on every request."""
    session.permanent = True

# JWT utils
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret')
JWT_ALGO = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30


def send_magic_link(email: str) -> None:
    """Send magic link to user's email, only if user already exists."""
    existing_user = db.get_user_by_email(email)

    if not existing_user:
        # Silently do nothing -- caller shows the same message either way
        return

    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)
    db.update_user_magic_token(email, token, expires)

    magic_url = f"{request.host_url.rstrip('/')}{url_for('magic_login', token=token)}"

    subject = "Login to New Favorite Child"
    body = f"""
    Click this link to log in to New Favorite Child:

    {magic_url}

    This link will expire in 1 hour.

    If you didn't request this, you can safely ignore this email.
    """

    send_email(email, subject, body)


def send_email(to_email: str, subject: str, body: str) -> None:
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
    msg['From'] = from_email or ""
    msg['To'] = to_email
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username or "", smtp_password or "")
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")


def send_favorite_child_notification(child_name: str, reason: str) -> None:
    """Send notification to all subscribed users about new favorite child."""
    subscribers = db.get_subscribed_users()
    
    for subscriber in subscribers:
        email = subscriber.email
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
    """UI: Home page showing current favorite child and subscribe form."""
    # Fetch data from API endpoints
    api_url = request.host_url.rstrip('/') + url_for('api_home_data')
    resp = requests.get(api_url)
    if resp.status_code == 200:
        data = resp.json()
        current_favorite = data.get('current_favorite')
        recent_history = data.get('recent_history')
    else:
        current_favorite = None
        recent_history = []
    return render_template('home.html', current_favorite=current_favorite, recent_history=recent_history)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    """UI: Add email to subscription list via API."""
    email = request.form.get('email', '').strip().lower()
    api_url = request.host_url.rstrip('/') + url_for('api_subscribe')
    resp = requests.post(api_url, json={'email': email})
    if resp.status_code == 200:
        flash(resp.json().get('message', 'Successfully subscribed!'), 'success')
    else:
        flash(resp.json().get('error', 'Subscription failed.'), 'error')
    return redirect(url_for('home'))


@app.route('/api/home', methods=['GET'])
def api_home_data():
    """API: Return current favorite child and recent history as JSON."""
    current_favorite = db.get_current_favorite_child()
    recent_history = db.get_recent_favorites(limit=5)
    # Convert datetimes to isoformat for JSON

    def serialize_fav(fav):
        if not fav:
            return None
        return {
            'id': fav.id,
            'name': fav.name,
            'reason': fav.reason,
            'timestamp': fav.timestamp.isoformat() if fav.timestamp else None
        }
    return jsonify({
        'current_favorite': serialize_fav(current_favorite),
        'recent_history': [serialize_fav(f) for f in recent_history]
    })


@app.route('/api/subscribe', methods=['POST'])
def api_subscribe():
    """API: Add email to subscription list."""
    data = request.get_json()
    email = data.get('email', '').strip().lower() if data else ''
    if not email or '@' not in email:
        return jsonify({'error': 'Please enter a valid email address.'}), 400
    existing_user = db.get_user_by_email(email)
    if existing_user:
        if existing_user.is_subscribed:
            return jsonify({'message': 'You are already subscribed!'}), 200
        else:
            existing_user.is_subscribed = True
            db.create_or_update_user(existing_user)
            return jsonify({'message': 'Welcome back! You have been resubscribed.'}), 200
    else:
        new_user = User(email=email, is_subscribed=True)
        db.create_or_update_user(new_user)
        return jsonify({'message': 'Successfully subscribed! You will receive notifications about new favorite children.'}), 200

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
    
    send_magic_link(email)
    flash('If this account exists, a login link has been sent to your email.', 'success')
    return redirect(url_for('login'))

@app.route('/magic_login/<token>')
def magic_login(token: str):
    """Handle magic link login."""
    print(f"🔗 Attempting magic login with token: {token[:10]}...")
    
    user = db.get_user_by_magic_token(token)
    
    if user:
        print(f"✅ Valid token found for user: {user.email}")
        # Clear the token
        db.clear_user_magic_token(user.email)
        
        session['user_email'] = user.email
        session['is_admin'] = user.is_admin
        session['is_editor'] = user.is_editor
        
        flash(f'Welcome back, {user.email}!', 'success')
        return redirect(url_for('home'))
    else:
        print(f"❌ Invalid or expired token: {token[:10]}...")
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
    user_email = cast(Optional[str], session.get('user_email'))
    if not user_email:
        flash('Please log in to access the admin panel.', 'error')
        return redirect(url_for('login'))
    
    is_admin = cast(Optional[bool], session.get('is_admin'))
    is_editor = cast(Optional[bool], session.get('is_editor'))
    if not (is_admin or is_editor):
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('home'))

    # Get all users
    users = db.get_all_users()
    
    # Get current favorite child
    current_favorite = db.get_current_favorite_child()
    
    return render_template('admin.html', users=users, current_favorite=current_favorite)

@app.route('/set_favorite', methods=['POST'])
def set_favorite():
    """Set new favorite child."""
    user_email = cast(Optional[str], session.get('user_email'))
    if not user_email:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))
    
    is_admin = cast(Optional[bool], session.get('is_admin'))
    is_editor = cast(Optional[bool], session.get('is_editor'))
    if not (is_admin or is_editor):
        flash('You do not have permission to set the favorite child.', 'error')
        return redirect(url_for('home'))
    
    child_name = request.form.get('child_name', '').strip()
    reason = request.form.get('reason', '').strip()
    
    if not child_name or not reason:
        flash('Please provide both a name and reason.', 'error')
        return redirect(url_for('admin'))
    
    # Add new favorite child
    db.add_favorite_child(name=child_name, reason=reason)
    
    # Send notifications
    send_favorite_child_notification(child_name, reason)
    
    flash(f'{child_name} is now the new favorite child!', 'success')
    return redirect(url_for('admin'))

@app.route('/add_user', methods=['POST'])
def add_user():
    """Add a new user (admin only)."""
    user_email = cast(Optional[str], session.get('user_email'))
    is_admin = cast(Optional[bool], session.get('is_admin'))
    if not user_email or not is_admin:
        flash('You do not have permission to add users.', 'error')
        return redirect(url_for('admin'))
    
    email = request.form.get('email', '').strip().lower()
    is_admin = 'is_admin' in request.form
    is_editor = 'is_editor' in request.form
    is_subscribed = 'is_subscribed' in request.form
    
    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('admin'))
    
    new_user = User(
        email=email,
        is_admin=is_admin,
        is_editor=is_editor,
        is_subscribed=is_subscribed
    )
    db.create_or_update_user(new_user)
    
    flash(f'User {email} has been added/updated.', 'success')
    return redirect(url_for('admin'))

@app.route('/delete_user', methods=['POST'])
def delete_user():
    """Delete a user (admin only)."""
    user_email = cast(Optional[str], session.get('user_email'))
    is_admin = cast(Optional[bool], session.get('is_admin'))
    if not user_email or not is_admin:
        flash('You do not have permission to delete users.', 'error')
        return redirect(url_for('admin'))

    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('No user specified.', 'error')
        return redirect(url_for('admin'))

    if email == user_email:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin'))

    db.delete_user(email)
    flash(f'User {email} has been deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/unsubscribe/<email>')
def unsubscribe(email: str):
    """Unsubscribe user from notifications."""
    db.unsubscribe_user(email)
    return render_template('unsubscribe.html', email=email)

@app.route('/history')
def history():
    """Show complete history of favorite children with stats."""
    page = request.args.get('page', 1, type=int)
    
    result = db.get_favorite_history(page=page, per_page=20)
    
    return render_template('history.html', 
                           history=result['history'],
                           stats=result['stats'],
                           fun_facts=result['fun_facts'],
                           page=result['pagination']['page'],
                           total_pages=result['pagination']['total_pages'],
                           has_prev=result['pagination']['has_prev'],
                           has_next=result['pagination']['has_next'],
                           total_count=result['pagination']['total_count'])

@app.route('/healthz')
def healthcheck():
    """Health check endpoint."""
    try:
        # Test database connection by getting current favorite
        db.get_current_favorite_child()
        
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


def create_access_token(email: str) -> str:
    payload = {
        'sub': email,
        'exp': datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_refresh_token(email: str) -> str:
    payload = {
        'sub': email,
        'exp': datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload['sub']
    except Exception:
        return None

# AUTH ENDPOINTS


@app.route('/api/auth/request_link', methods=['POST'])
def api_request_link():
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    email = request.json.get('email', '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'error': 'Invalid email'}), 400

    existing_user = db.get_user_by_email(email)
    if existing_user:
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(hours=1)
        db.update_user_magic_token(email, token, expires)

        magic_url = f"newfavoritechild://confirm?token={token}"
        subject = "Login to New Favorite Child"
        body = f"Click this link to log in: {magic_url}\nThis link will expire in 1 hour."
        send_email(email, subject, body)

    # Always return the same response to prevent email enumeration
    return jsonify({'message': 'If this account exists, a login link has been sent.'})


@app.route('/api/auth/confirm', methods=['POST'])
def api_confirm():
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    token = request.json.get('token')
    user = db.get_user_by_magic_token(token)

    if user:
        db.clear_user_magic_token(user.email)
        access_token = create_access_token(user.email)
        refresh_token = create_refresh_token(user.email)
        return jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'email': user.email
        })
    else:
        return jsonify({'error': 'Invalid or expired token'}), 400


@app.route('/api/auth/refresh', methods=['POST'])
def api_refresh():
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    refresh_token = request.json.get('refresh_token')
    email = verify_token(refresh_token)
    if not email:
        return jsonify({'error': 'Invalid refresh token'}), 401

    access_token = create_access_token(email)
    return jsonify({'access_token': access_token})

# FAMILY ENDPOINTS


def generate_family_code() -> str:
    return ''.join(choices(string.ascii_letters + string.digits, k=6))


@app.route('/api/families', methods=['POST'])
def create_family():
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    data = request.json
    name = data.get('name')
    owner_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))

    if not owner_email:
        return jsonify({'error': 'Unauthorized'}), 401

    if not name:
        return jsonify({'error': 'Family name is required'}), 400

    family = db.create_family(name=name, owner_email=owner_email)
    return jsonify({'id': family.id, 'name': family.name, 'code': family.code})


@app.route('/api/families/join', methods=['POST'])
def join_family():
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    data = request.json
    code = data.get('code')
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))

    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    if not code:
        return jsonify({'error': 'Family code is required'}), 400

    family = db.get_family_by_code(code)
    if not family:
        return jsonify({'error': 'Invalid code'}), 404

    db.add_family_member(user_email=user_email,
                         family_id=family.id, role='member')
    return jsonify({'message': 'Joined family'})


@app.route('/api/families', methods=['GET'])
def list_families():
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    families = db.get_user_families(user_email)
    return jsonify({'families': families})


@app.route('/api/families/<int:family_id>', methods=['GET'])
def family_details(family_id: int):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    family_details = db.get_family_details(family_id)
    if not family_details:
        return jsonify({'error': 'Not found'}), 404

    return jsonify(family_details)


@app.route('/api/families/<int:family_id>/favorite', methods=['POST'])
def set_favorite_child(family_id: int):
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    role = db.get_user_family_role(user_email, family_id)
    if not role or role not in ('owner', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json
    name = data.get('name')
    reason = data.get('reason')

    if not name or not reason:
        return jsonify({'error': 'Name and reason are required'}), 400

    db.add_favorite_child(
        name=name,
        reason=reason,
        family_id=family_id,
        set_by=user_email
    )
    return jsonify({'message': 'Favorite child set'})


@app.route('/api/families/<int:family_id>/history', methods=['GET'])
def favorite_history(family_id: int):
    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    history = db.get_family_favorite_history(family_id)
    return jsonify({'history': history})


@app.route('/api/families/<int:family_id>/roles', methods=['POST'])
def assign_role(family_id: int):
    if not request.json:
        return jsonify({'error': 'Invalid request'}), 400

    user_email = verify_token(request.headers.get(
        'Authorization', '').replace('Bearer ', ''))
    if not user_email:
        return jsonify({'error': 'Unauthorized'}), 401

    # Only owner can assign roles
    role = db.get_user_family_role(user_email, family_id)
    if not role or role != 'owner':
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json
    target_email = data.get('user_email')
    new_role = data.get('role')

    if not target_email or not new_role:
        return jsonify({'error': 'User email and role are required'}), 400

    if new_role not in ('admin', 'member'):
        return jsonify({'error': 'Invalid role'}), 400

    db.update_family_member_role(target_email, family_id, new_role)
    return jsonify({'message': 'Role updated'})

if __name__ == '__main__':
    db.init_db()
    port = int(os.environ.get('PORT', 5003))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=port) 
