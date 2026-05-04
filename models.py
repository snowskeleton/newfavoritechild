from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
import sqlite3
import os
from datetime import datetime, timedelta
import secrets


@dataclass
class User:
    email: str
    is_admin: bool = False
    is_editor: bool = False
    is_subscribed: bool = True
    magic_token: Optional[str] = None
    token_expires: Optional[datetime] = None


@dataclass
class FavoriteChild:
    id: Optional[int] = None
    name: str = ""
    reason: str = ""
    timestamp: Optional[datetime] = None


@dataclass
class Family:
    id: Optional[int] = None
    name: str = ""
    code: str = ""
    owner_email: str = ""


@dataclass
class FamilyMember:
    user_email: str = ""
    family_id: int = 0
    role: str = "member"  # "owner", "admin", "member"


class DatabaseManager:
    def __init__(self, database_path: str = None):
        self.database_path = database_path or os.environ.get('DATABASE_PATH', 'newfavoritechild.db')
    
    def get_connection(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        """Initialize the database with required tables."""
        conn = sqlite3.connect(self.database_path)
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
                family_id INTEGER,
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
    
    # User operations
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return User(
                email=row['email'],
                is_admin=bool(row['is_admin']),
                is_editor=bool(row['is_editor']),
                is_subscribed=bool(row['is_subscribed']),
                magic_token=row['magic_token'],
                token_expires=datetime.fromisoformat(row['token_expires']) if row['token_expires'] else None
            )
        return None
    
    def create_or_update_user(self, user: User) -> None:
        """Create or update a user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (email, is_admin, is_editor, is_subscribed, magic_token, token_expires)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user.email, user.is_admin, user.is_editor, user.is_subscribed, user.magic_token, user.token_expires))
        conn.commit()
        conn.close()
    
    def update_user_magic_token(self, email: str, token: str, expires: datetime) -> None:
        """Update user's magic token."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET magic_token = ?, token_expires = ?
            WHERE email = ?
        ''', (token, expires, email))
        conn.commit()
        conn.close()
    
    def clear_user_magic_token(self, email: str) -> None:
        """Clear user's magic token."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET magic_token = NULL, token_expires = NULL 
            WHERE email = ?
        ''', (email,))
        conn.commit()
        conn.close()
    
    def get_user_by_magic_token(self, token: str) -> Optional[User]:
        """Get user by magic token if valid."""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute('''
            SELECT * FROM users 
            WHERE magic_token = ? AND token_expires > ?
        ''', (token, now))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return User(
                email=row['email'],
                is_admin=bool(row['is_admin']),
                is_editor=bool(row['is_editor']),
                is_subscribed=bool(row['is_subscribed']),
                magic_token=row['magic_token'],
                token_expires=datetime.fromisoformat(row['token_expires']) if row['token_expires'] else None
            )
        return None
    
    def get_subscribed_users(self) -> List[User]:
        """Get all subscribed users."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE is_subscribed = TRUE')
        rows = cursor.fetchall()
        conn.close()
        
        return [
            User(
                email=row['email'],
                is_admin=bool(row['is_admin']),
                is_editor=bool(row['is_editor']),
                is_subscribed=bool(row['is_subscribed']),
                magic_token=row['magic_token'],
                token_expires=datetime.fromisoformat(row['token_expires']) if row['token_expires'] else None
            )
            for row in rows
        ]
    
    def unsubscribe_user(self, email: str) -> None:
        """Unsubscribe a user from notifications."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_subscribed = FALSE WHERE email = ?', (email,))
        conn.commit()
        conn.close()
    
    def delete_user(self, email: str) -> None:
        """Delete a user by email."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM family_members WHERE user_email = ?', (email,))
        cursor.execute('DELETE FROM users WHERE email = ?', (email,))
        conn.commit()
        conn.close()

    def get_all_users(self) -> List[User]:
        """Get all users."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY email')
        rows = cursor.fetchall()
        conn.close()
        
        return [
            User(
                email=row['email'],
                is_admin=bool(row['is_admin']),
                is_editor=bool(row['is_editor']),
                is_subscribed=bool(row['is_subscribed']),
                magic_token=row['magic_token'],
                token_expires=datetime.fromisoformat(row['token_expires']) if row['token_expires'] else None
            )
            for row in rows
        ]
    
    # Favorite Child operations
    def get_current_favorite_child(self, family_id: Optional[int] = None) -> Optional[FavoriteChild]:
        """Get the current favorite child."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if family_id:
            cursor.execute('SELECT * FROM favorite_child WHERE family_id = ? ORDER BY timestamp DESC LIMIT 1', (family_id,))
        else:
            cursor.execute('SELECT * FROM favorite_child ORDER BY timestamp DESC LIMIT 1')
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return FavoriteChild(
                id=row['id'],
                name=row['name'],
                reason=row['reason'],
                timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None
            )
        return None
    
    def add_favorite_child(self, name: str, reason: str, family_id: Optional[int] = None, set_by: Optional[str] = None) -> FavoriteChild:
        """Add a new favorite child."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if family_id:
            cursor.execute('''
                INSERT INTO favorite_child (family_id, name, reason, set_by)
                VALUES (?, ?, ?, ?)
            ''', (family_id, name, reason, set_by))
        else:
            cursor.execute('''
                INSERT INTO favorite_child (name, reason)
                VALUES (?, ?)
            ''', (name, reason))
        
        favorite_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return FavoriteChild(
            id=favorite_id,
            name=name,
            reason=reason,
            timestamp=datetime.now()
        )
    
    def get_recent_favorites(self, limit: int = 5, family_id: Optional[int] = None) -> List[FavoriteChild]:
        """Get recent favorite children."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if family_id:
            cursor.execute('''
                SELECT * FROM favorite_child 
                WHERE family_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (family_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM favorite_child 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            FavoriteChild(
                id=row['id'],
                name=row['name'],
                reason=row['reason'],
                timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None
            )
            for row in rows
        ]
    
    def get_favorite_history(self, page: int = 1, per_page: int = 20, family_id: Optional[int] = None) -> Dict[str, Any]:
        """Get paginated favorite child history."""
        conn = self.get_connection()
        cursor = conn.cursor()
        offset = (page - 1) * per_page
        
        # Get total count
        if family_id:
            cursor.execute('SELECT COUNT(*) as total FROM favorite_child WHERE family_id = ?', (family_id,))
        else:
            cursor.execute('SELECT COUNT(*) as total FROM favorite_child')
        total_count = cursor.fetchone()['total']
        
        # Get paginated history
        if family_id:
            cursor.execute('''
                SELECT * FROM favorite_child 
                WHERE family_id = ?
                ORDER BY timestamp DESC 
                LIMIT ? OFFSET ?
            ''', (family_id, per_page, offset))
        else:
            cursor.execute('''
                SELECT * FROM favorite_child 
                ORDER BY timestamp DESC 
                LIMIT ? OFFSET ?
            ''', (per_page, offset))
        
        history_rows = cursor.fetchall()
        
        # Get stats
        if family_id:
            cursor.execute('''
                SELECT 
                    name,
                    COUNT(*) as times_crowned,
                    MIN(timestamp) as first_crowned,
                    MAX(timestamp) as last_crowned,
                    GROUP_CONCAT(reason, '|') as all_reasons
                FROM favorite_child 
                WHERE family_id = ?
                GROUP BY name 
                ORDER BY times_crowned DESC, last_crowned DESC
            ''', (family_id,))
        else:
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
        
        stats_rows = cursor.fetchall()
        
        # Get fun facts
        if family_id:
            cursor.execute('''
                SELECT 
                    (SELECT COUNT(DISTINCT name) FROM favorite_child WHERE family_id = ?) as unique_favorites,
                    (SELECT COUNT(*) FROM favorite_child WHERE family_id = ?) as total_crownings,
                    (SELECT name FROM favorite_child WHERE family_id = ? ORDER BY timestamp ASC LIMIT 1) as first_ever,
                    (SELECT name FROM favorite_child WHERE family_id = ? ORDER BY timestamp DESC LIMIT 1) as current_favorite
            ''', (family_id, family_id, family_id, family_id))
        else:
            cursor.execute('''
                SELECT 
                    (SELECT COUNT(DISTINCT name) FROM favorite_child) as unique_favorites,
                    (SELECT COUNT(*) FROM favorite_child) as total_crownings,
                    (SELECT name FROM favorite_child ORDER BY timestamp ASC LIMIT 1) as first_ever,
                    (SELECT name FROM favorite_child ORDER BY timestamp DESC LIMIT 1) as current_favorite
            ''')
        
        fun_facts = cursor.fetchone()
        conn.close()
        
        # Calculate pagination
        total_pages = (total_count + per_page - 1) // per_page
        
        return {
            'history': [
                FavoriteChild(
                    id=row['id'],
                    name=row['name'],
                    reason=row['reason'],
                    timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None
                )
                for row in history_rows
            ],
            'stats': [dict(row) for row in stats_rows],
            'fun_facts': dict(fun_facts) if fun_facts else {},
            'pagination': {
                'page': page,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'total_count': total_count
            }
        }
    
    # Family operations
    def create_family(self, name: str, owner_email: str) -> Family:
        """Create a new family."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Generate unique code
        code = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))
        
        cursor.execute('''
            INSERT INTO families (name, code, owner_email)
            VALUES (?, ?, ?)
        ''', (name, code, owner_email))
        
        family_id = cursor.lastrowid
        
        # Add owner as family member
        cursor.execute('''
            INSERT INTO family_members (user_email, family_id, role)
            VALUES (?, ?, ?)
        ''', (owner_email, family_id, 'owner'))
        
        conn.commit()
        conn.close()
        
        return Family(
            id=family_id,
            name=name,
            code=code,
            owner_email=owner_email
        )
    
    def get_family_by_code(self, code: str) -> Optional[Family]:
        """Get family by code."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM families WHERE code = ?', (code,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Family(
                id=row['id'],
                name=row['name'],
                code=row['code'],
                owner_email=row['owner_email']
            )
        return None
    
    def get_user_families(self, user_email: str) -> List[Dict[str, Any]]:
        """Get all families a user belongs to."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT f.id, f.name, f.code, fm.role 
            FROM families f 
            JOIN family_members fm ON f.id = fm.family_id 
            WHERE fm.user_email = ?
        ''', (user_email,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_family_details(self, family_id: int) -> Optional[Dict[str, Any]]:
        """Get family details with members and current favorite."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get family info
        cursor.execute('SELECT * FROM families WHERE id = ?', (family_id,))
        family_row = cursor.fetchone()
        
        if not family_row:
            conn.close()
            return None
        
        # Get members
        cursor.execute('SELECT user_email, role FROM family_members WHERE family_id = ?', (family_id,))
        member_rows = cursor.fetchall()
        
        # Get current favorite
        cursor.execute('''
            SELECT * FROM favorite_child 
            WHERE family_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
        ''', (family_id,))
        favorite_row = cursor.fetchone()
        
        conn.close()
        
        return {
            'family': dict(family_row),
            'members': [dict(row) for row in member_rows],
            'current_favorite': dict(favorite_row) if favorite_row else None
        }
    
    def add_family_member(self, user_email: str, family_id: int, role: str = 'member') -> None:
        """Add a user to a family."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO family_members (user_email, family_id, role)
            VALUES (?, ?, ?)
        ''', (user_email, family_id, role))
        conn.commit()
        conn.close()
    
    def get_user_family_role(self, user_email: str, family_id: int) -> Optional[str]:
        """Get user's role in a family."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT role FROM family_members 
            WHERE user_email = ? AND family_id = ?
        ''', (user_email, family_id))
        row = cursor.fetchone()
        conn.close()
        
        return row['role'] if row else None
    
    def update_family_member_role(self, user_email: str, family_id: int, new_role: str) -> None:
        """Update a family member's role."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE family_members 
            SET role = ? 
            WHERE user_email = ? AND family_id = ?
        ''', (new_role, user_email, family_id))
        conn.commit()
        conn.close()
    
    def get_family_favorite_history(self, family_id: int) -> List[Dict[str, Any]]:
        """Get favorite child history for a family."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, reason, timestamp, set_by 
            FROM favorite_child 
            WHERE family_id = ? 
            ORDER BY timestamp DESC
        ''', (family_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# Global database manager instance
db = DatabaseManager() 
