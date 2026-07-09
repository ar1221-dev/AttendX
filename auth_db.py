import os
import secrets
import re
import bcrypt
from datetime import datetime, timedelta
import db_engine

def get_db():
    return db_engine.get_connection()


def init_db():
    db_engine.init_tables()


def create_user(email, username, password, role='user', full_name='', is_active=True):
    password_hash = hash_password(password)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO users (username, email, password_hash, role, full_name, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (username.strip(), email.strip().lower(), password_hash, role, full_name.strip(), 1 if is_active else 0)
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?;', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_username_or_email(identifier):
    conn = get_db()
    identifier = identifier.strip().lower()
    user = conn.execute(
        'SELECT * FROM users WHERE lower(username) = ? OR lower(email) = ?;',
        (identifier, identifier)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE lower(email) = ?;', (email.strip().lower(),)).fetchone()
    conn.close()
    return dict(user) if user else None


def verify_password(password, password_hash):
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def validate_password(password):
    if len(password) < 12:
        return False, 'Password must be at least 12 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must include an uppercase letter.'
    if not re.search(r'[a-z]', password):
        return False, 'Password must include a lowercase letter.'
    if not re.search(r'\d', password):
        return False, 'Password must include a number.'
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, 'Password must include a special character.'
    return True, ''


def update_last_login(user_id):
    conn = get_db()
    conn.execute('UPDATE users SET last_login_at = ? WHERE id = ?;', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def set_user_status(user_id, active):
    conn = get_db()
    conn.execute('UPDATE users SET is_active = ? WHERE id = ?;', (1 if active else 0, user_id))
    conn.commit()
    conn.close()


def is_account_active(user_id):
    conn = get_db()
    row = conn.execute('SELECT is_active FROM users WHERE id = ?;', (user_id,)).fetchone()
    conn.close()
    return bool(row and row['is_active'])


def delete_user(user_id):
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id = ?;', (user_id,))
    conn.commit()
    conn.close()


def get_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC;').fetchall()
    conn.close()
    return [dict(row) for row in users]


def create_invitation(email, created_by=None, expires_days=7):
    token = secrets.token_urlsafe(24)
    expires_at = (datetime.now() + timedelta(days=expires_days)).strftime('%Y-%m-%d %H:%M:%S')
    token_hash = bcrypt.hashpw(token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO invitations (email, token_hash, token, expires_at, status, created_by) VALUES (?, ?, ?, ?, ?, ?);',
        (email.strip().lower(), token_hash, token, expires_at, 'pending', created_by)
    )
    conn.commit()
    invitation_id = cursor.lastrowid
    conn.close()
    return invitation_id, token


def get_invitations():
    conn = get_db()
    rows = conn.execute('SELECT * FROM invitations ORDER BY created_at DESC;').fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_valid_invitation(token):
    conn = get_db()
    rows = conn.execute('SELECT * FROM invitations ORDER BY created_at DESC;').fetchall()
    conn.close()
    now = datetime.now()
    for row in rows:
        if row['status'] != 'pending':
            continue
        if row['used_at'] or row['cancelled_at']:
            continue
        try:
            expires_at = datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            expires_at = datetime.min
        if expires_at <= now:
            continue
        if bcrypt.checkpw(token.encode('utf-8'), row['token_hash'].encode('utf-8')):
            return dict(row)
    return None


def mark_invitation_used(invitation_id):
    conn = get_db()
    conn.execute('UPDATE invitations SET status = ?, used_at = ? WHERE id = ?;', ('accepted', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), invitation_id))
    conn.commit()
    conn.close()


def cancel_invitation(invitation_id):
    conn = get_db()
    conn.execute('UPDATE invitations SET status = ?, cancelled_at = ? WHERE id = ?;', ('cancelled', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), invitation_id))
    conn.commit()
    conn.close()


def delete_invitation(invitation_id):
    conn = get_db()
    conn.execute('DELETE FROM invitations WHERE id = ?;', (invitation_id,))
    conn.commit()
    conn.close()


def expire_old_invitations():
    conn = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("UPDATE invitations SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?;", (now,))
    conn.commit()
    conn.close()


def create_password_reset(user_id):
    token = secrets.token_urlsafe(24)
    expires_at = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    token_hash = bcrypt.hashpw(token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?, ?, ?);', (user_id, token_hash, expires_at))
    conn.commit()
    reset_id = cursor.lastrowid
    conn.close()
    return reset_id, token


def get_valid_password_reset(token):
    conn = get_db()
    rows = conn.execute('SELECT * FROM password_resets ORDER BY created_at DESC;').fetchall()
    conn.close()
    now = datetime.now()
    for row in rows:
        if row['used_at']:
            continue
        try:
            expires_at = datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            expires_at = datetime.min
        if expires_at <= now:
            continue
        if bcrypt.checkpw(token.encode('utf-8'), row['token_hash'].encode('utf-8')):
            return dict(row)
    return None


def mark_password_reset_used(reset_id):
    conn = get_db()
    conn.execute('UPDATE password_resets SET used_at = ? WHERE id = ?;', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), reset_id))
    conn.commit()
    conn.close()


def update_password(user_id, password):
    conn = get_db()
    conn.execute('UPDATE users SET password_hash = ? WHERE id = ?;', (hash_password(password), user_id))
    conn.commit()
    conn.close()


def update_user_profile(user_id, username, email, full_name):
    username = username.strip()
    email = email.strip().lower()
    full_name = full_name.strip()
    
    conn = get_db()
    try:
        # Check if username is taken by another user
        existing_user = conn.execute('SELECT id FROM users WHERE lower(username) = ? AND id != ?;', (username.lower(), user_id)).fetchone()
        if existing_user:
            return False, 'Username is already taken.'
            
        # Check if email is taken by another user
        existing_email = conn.execute('SELECT id FROM users WHERE lower(email) = ? AND id != ?;', (email.lower(), user_id)).fetchone()
        if existing_email:
            return False, 'Email is already in use.'
            
        conn.execute(
            'UPDATE users SET username = ?, email = ?, full_name = ? WHERE id = ?;',
            (username, email, full_name, user_id)
        )
        conn.commit()
        return True, 'Profile updated successfully.'
    except sqlite3.Error as e:
        return False, f'Database error: {str(e)}'
    finally:
        conn.close()


def get_invitation_by_id(invitation_id):
    conn = get_db()
    invitation = conn.execute('SELECT * FROM invitations WHERE id = ?;', (invitation_id,)).fetchone()
    conn.close()
    return dict(invitation) if invitation else None
