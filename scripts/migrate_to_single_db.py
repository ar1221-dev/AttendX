import os
import sqlite3
from datetime import datetime

def run_migration():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_dir = os.environ.get('DATABASE_DIR', base_dir)
    
    old_auth_path = os.path.join(db_dir, 'auth.db')
    new_db_path = os.path.join(db_dir, 'attendance.db')
    
    if not os.path.exists(old_auth_path):
        print("No old auth.db found. Skipping structural migration.")
        return
        
    print("Found old databases. Initializing migration to single database structure...")
    
    # Initialize the new unified database tables first
    import sys
    sys.path.append(base_dir)
    import db_engine
    db_engine.init_tables()
    
    # Connect to new unified database
    new_conn = sqlite3.connect(new_db_path)
    new_conn.row_factory = sqlite3.Row
    new_cursor = new_conn.cursor()
    
    # 1. Migrate Auth Database
    old_auth_conn = sqlite3.connect(old_auth_path)
    old_auth_conn.row_factory = sqlite3.Row
    old_auth_cursor = old_auth_conn.cursor()
    
    # Migrate users
    old_auth_cursor.execute("SELECT * FROM users;")
    users = old_auth_cursor.fetchall()
    for u in users:
        new_cursor.execute("""
            INSERT OR IGNORE INTO users (id, username, email, password_hash, role, full_name, is_active, created_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (u['id'], u['username'], u['email'], u['password_hash'], u['role'], u['full_name'], u['is_active'], u['created_at'], u['last_login_at']))
    print(f"Migrated {len(users)} users.")
    
    # Migrate invitations
    try:
        old_auth_cursor.execute("SELECT * FROM invitations;")
        invitations = old_auth_cursor.fetchall()
        for i in invitations:
            new_cursor.execute("""
                INSERT OR IGNORE INTO invitations (id, email, token_hash, token, created_at, expires_at, used_at, cancelled_at, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (i['id'], i['email'], i['token_hash'], i.get('token'), i['created_at'], i['expires_at'], i['used_at'], i['cancelled_at'], i['status'], i['created_by']))
        print(f"Migrated {len(invitations)} invitations.")
    except Exception as e:
        print("No invitations migrated or table not present:", e)
        
    # Migrate password resets
    try:
        old_auth_cursor.execute("SELECT * FROM password_resets;")
        resets = old_auth_cursor.fetchall()
        for r in resets:
            new_cursor.execute("""
                INSERT OR IGNORE INTO password_resets (id, user_id, token_hash, created_at, expires_at, used_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (r['id'], r['user_id'], r['token_hash'], r['created_at'], r['expires_at'], r['used_at']))
        print(f"Migrated {len(resets)} password resets.")
    except Exception as e:
        print("No password resets migrated or table not present:", e)
        
    old_auth_conn.close()
    
    # 2. Migrate User Specific Databases
    for u in users:
        user_id = u['id']
        old_user_db_path = os.path.join(db_dir, f'attendance_user_{user_id}.db')
        if not os.path.exists(old_user_db_path):
            continue
            
        print(f"Migrating database for user {user_id}...")
        u_conn = sqlite3.connect(old_user_db_path)
        u_conn.row_factory = sqlite3.Row
        u_cursor = u_conn.cursor()
        
        # Helper to migrate table
        def migrate_table(table_name, columns, has_id=True):
            try:
                u_cursor.execute(f"SELECT * FROM {table_name};")
                rows = u_cursor.fetchall()
                for r in rows:
                    col_placeholders = ', '.join(['?'] * (len(columns) + 1))
                    col_names = ', '.join(['user_id'] + columns)
                    val_tuple = [user_id] + [r[c] for c in columns]
                    
                    if has_id:
                        col_names = 'id, ' + col_names
                        col_placeholders = '?, ' + col_placeholders
                        val_tuple = [r['id']] + val_tuple
                        
                    query = f"INSERT OR IGNORE INTO {table_name} ({col_names}) VALUES ({col_placeholders});"
                    new_cursor.execute(query, val_tuple)
                print(f"  - Migrated {len(rows)} rows from {table_name}.")
            except Exception as e:
                print(f"  - Error migrating {table_name}: {e}")
                
        migrate_table('semesters', ['name', 'start_date', 'end_date', 'target', 'working_days', 'notes'])
        migrate_table('subjects', ['semester_id', 'name', 'code', 'faculty', 'credits'])
        migrate_table('timetable_versions', ['semester_id', 'version_name', 'effective_date', 'end_date'])
        migrate_table('timetable_entries', ['version_id', 'subject_id', 'day_of_week', 'start_time', 'end_time', 'room', 'notes'])
        migrate_table('attendance', ['semester_id', 'subject_id', 'date', 'time', 'status', 'version_id', 'notes'])
        migrate_table('holidays', ['semester_id', 'date', 'reason'])
        migrate_table('no_class_days', ['semester_id', 'date', 'reason', 'custom_description'])
        migrate_table('settings', ['key', 'value'], has_id=False)
        migrate_table('backup_history', ['backup_time', 'filename', 'status'])
        migrate_table('cancelled_classes', ['semester_id', 'subject_id', 'date', 'reason'])
        migrate_table('extra_class_days', ['semester_id', 'date', 'day_to_follow', 'reason'])
        
        u_conn.close()
        
    new_conn.commit()
    new_conn.close()
    
    # 3. Rename old files to prevent double migration
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.rename(old_auth_path, old_auth_path + f'.{timestamp}.bak')
    print(f"Renamed auth.db to auth.db.{timestamp}.bak")
    
    for u in users:
        user_id = u['id']
        old_user_db_path = os.path.join(db_dir, f'attendance_user_{user_id}.db')
        if os.path.exists(old_user_db_path):
            os.rename(old_user_db_path, old_user_db_path + f'.{timestamp}.bak')
            print(f"Renamed attendance_user_{user_id}.db to attendance_user_{user_id}.db.{timestamp}.bak")
            
    print("Migration completed successfully!")

if __name__ == '__main__':
    run_migration()
