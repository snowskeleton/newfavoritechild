# 👑 New Favorite Child

A fun web application that lets your mother (or any designated editor) set a new favorite child and notify everyone via email! Built with Python Flask and featuring magic link authentication.

## Features

- **👑 Set Favorite Child**: Designated editors can crown a new favorite child with a reason
- **📧 Email Notifications**: All subscribers receive email notifications when a new favorite is crowned
- **🔐 Magic Link Authentication**: Secure, passwordless login via email links
- **👥 User Management**: Admins can add users and manage permissions
- **📝 Subscription Management**: Users can subscribe/unsubscribe from notifications
- **🏥 Health Check**: `/healthz` endpoint for monitoring
- **💾 SQLite Database**: Persistent data storage
- **🎨 Beautiful UI**: Modern, responsive design

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Flask secret key (auto-generated if not set)
SECRET_KEY=your-secret-key-here

# Fastmail SMTP settings
SMTP_SERVER=smtp.fastmail.com
SMTP_PORT=587
SMTP_USERNAME=your-fastmail-username
SMTP_PASSWORD=your-fastmail-password
FROM_EMAIL=your-fastmail-username@fastmail.com
```

### 3. Run the Application

```bash
python app.py
```

The app will be available at `http://localhost:5000`

## Usage

### First Time Setup

1. **Create Admin User**: The first time you run the app, you'll need to manually add an admin user to the database:

```python
import sqlite3
conn = sqlite3.connect('newfavoritechild.db')
cursor = conn.cursor()
cursor.execute('''
    INSERT INTO users (email, is_admin, is_editor, is_subscribed)
    VALUES ('your-email@example.com', TRUE, TRUE, TRUE)
''')
conn.commit()
conn.close()
```

2. **Add Your Mother as Editor**: Use the admin panel to add your mother's email as an editor (can set favorite child but not manage users).

### User Roles

- **Regular Users**: Can subscribe to notifications
- **Editors**: Can set new favorite children (like your mother)
- **Admins**: Can manage users and set favorite children

### Magic Link Authentication

1. Click "Login" on the homepage
2. Enter your email address
3. Check your email for a secure login link
4. Click the link to automatically log in
5. Links expire after 1 hour

## API Endpoints

- `GET /` - Homepage with current favorite child and subscription form
- `POST /subscribe` - Subscribe to email notifications
- `GET /login` - Login page
- `POST /request_login` - Request magic link
- `GET /magic_login/<token>` - Magic link authentication
- `GET /logout` - Logout
- `GET /admin` - Admin panel (requires login)
- `POST /set_favorite` - Set new favorite child (requires editor/admin)
- `POST /add_user` - Add new user (admin only)
- `GET /unsubscribe/<email>` - Unsubscribe from notifications
- `GET /healthz` - Health check endpoint

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    email TEXT PRIMARY KEY,
    is_admin BOOLEAN DEFAULT FALSE,
    is_editor BOOLEAN DEFAULT FALSE,
    is_subscribed BOOLEAN DEFAULT TRUE,
    magic_token TEXT,
    token_expires DATETIME
);
```

### Favorite Child Table
```sql
CREATE TABLE favorite_child (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    reason TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Email Configuration

The app uses Fastmail SMTP for sending emails. You'll need:

1. A Fastmail account
2. SMTP credentials (username/password)
3. Configure the environment variables listed above

## Development

### Running in Development Mode

```bash
export FLASK_ENV=development
python app.py
```

### Database Reset

To reset the database:

```bash
rm newfavoritechild.db
python app.py  # This will recreate the database
```

## Security Features

- Magic link authentication (no passwords stored)
- Token expiration (1 hour)
- SQL injection protection via parameterized queries
- CSRF protection via Flask's built-in features
- Secure session management

## Contributing

This is a fun family project! Feel free to add features like:
- Email templates
- Notification history
- Favorite child statistics
- Mobile app
- Integration with family calendar

## License

Built with ❤️ and a dash of sibling rivalry. 
