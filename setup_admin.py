#!/usr/bin/env python3
"""
Setup script to create the initial admin user for New Favorite Child.
Run this after setting up your environment variables.
"""

import sqlite3
import sys

def setup_admin():
    """Create the initial admin user."""
    try:
        # Get admin email from user
        admin_email = input("Enter your email address (for admin access): ").strip().lower()
        
        if not admin_email or '@' not in admin_email:
            print("❌ Please enter a valid email address.")
            return False
        
        # Connect to database
        conn = sqlite3.connect('newfavoritechild.db')
        cursor = conn.cursor()
        
        # Check if user already exists
        cursor.execute('SELECT * FROM users WHERE email = ?', (admin_email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            # Update existing user to be admin
            cursor.execute('''
                UPDATE users 
                SET is_admin = TRUE, is_editor = TRUE, is_subscribed = TRUE
                WHERE email = ?
            ''', (admin_email,))
            print(f"✅ Updated {admin_email} to admin privileges.")
        else:
            # Create new admin user
            cursor.execute('''
                INSERT INTO users (email, is_admin, is_editor, is_subscribed)
                VALUES (?, TRUE, TRUE, TRUE)
            ''', (admin_email,))
            print(f"✅ Created admin user: {admin_email}")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 Setup complete!")
        print(f"You can now log in as {admin_email} using magic link authentication.")
        print("Run 'python app.py' to start the application.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error setting up admin user: {e}")
        return False

if __name__ == '__main__':
    print("👑 New Favorite Child - Admin Setup")
    print("=" * 40)
    
    success = setup_admin()
    
    if not success:
        sys.exit(1) 
