"""
Transfer data from one user to another in the Attendance App.
Usage: python transfer_data.py <source_username> <target_username>
"""

import sqlite3
import os
import sys

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_db
import database as db


def get_user_by_username(username):
    """Get user info by username"""
    conn = auth_db.get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE lower(username) = ?;',
        (username.lower(),)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def copy_table_data(source_conn, target_conn, table_name):
    """Copy all data from one table in source DB to target DB"""
    try:
        # Get all data from source table
        cursor = source_conn.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        
        if not rows:
            print(f"  ✓ {table_name}: No data to copy")
            return 0
        
        # Get column names
        column_names = [description[0] for description in cursor.description]
        
        # Delete existing data in target table (except IDs to maintain integrity)
        target_conn.execute(f"DELETE FROM {table_name}")
        
        # Insert data into target table
        placeholders = ', '.join(['?' for _ in column_names])
        insert_query = f"INSERT INTO {table_name} ({', '.join(column_names)}) VALUES ({placeholders})"
        
        for row in rows:
            try:
                target_conn.execute(insert_query, row)
            except sqlite3.IntegrityError as e:
                print(f"    Warning: Could not copy record in {table_name}: {e}")
                continue
        
        target_conn.commit()
        print(f"  ✓ {table_name}: Copied {len(rows)} records")
        return len(rows)
        
    except sqlite3.OperationalError as e:
        print(f"  ✗ {table_name}: {e}")
        return 0


def transfer_data(source_user_id, target_user_id):
    """Transfer all data from source user to target user"""
    
    # Get database paths
    source_db_path = db.get_user_db_path(source_user_id)
    target_db_path = db.get_user_db_path(target_user_id)
    
    # Check if source database exists
    if not os.path.exists(source_db_path):
        print(f"❌ Error: Source database not found at {source_db_path}")
        return False
    
    # Ensure target database exists
    db.ensure_user_db(target_user_id)
    
    if not os.path.exists(target_db_path):
        print(f"❌ Error: Could not create target database at {target_db_path}")
        return False
    
    # Connect to both databases
    source_conn = sqlite3.connect(source_db_path)
    target_conn = sqlite3.connect(target_db_path)
    
    source_conn.execute("PRAGMA foreign_keys = OFF")
    target_conn.execute("PRAGMA foreign_keys = OFF")
    
    # List of tables to copy
    tables_to_copy = [
        'semesters',
        'subjects',
        'timetable_versions',
        'timetable_entries',
        'attendance',
        'holidays',
        'no_class_days',
        'cancelled_classes',
        'settings'
    ]
    
    print(f"\n📦 Starting data transfer...")
    print(f"From: User ID {source_user_id}")
    print(f"To: User ID {target_user_id}\n")
    
    total_records = 0
    
    for table in tables_to_copy:
        records = copy_table_data(source_conn, target_conn, table)
        total_records += records
    
    # Re-enable foreign keys
    source_conn.execute("PRAGMA foreign_keys = ON")
    target_conn.execute("PRAGMA foreign_keys = ON")
    
    source_conn.close()
    target_conn.close()
    
    print(f"\n✅ Data transfer complete!")
    print(f"Total records transferred: {total_records}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transfer_data.py <source_username> <target_username>")
        print("\nExample: python transfer_data.py admin raj")
        sys.exit(1)
    
    source_username = sys.argv[1]
    target_username = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Initialize auth database
    auth_db.init_db()
    
    # Get source user
    source_user = get_user_by_username(source_username)
    if not source_user:
        print(f"❌ Error: User '{source_username}' not found in system")
        sys.exit(1)
    
    source_user_id = source_user['id']
    
    # Get target user
    if not target_username:
        target_username = "raj"
    
    target_user = get_user_by_username(target_username)
    if not target_user:
        print(f"❌ Error: User '{target_username}' not found in system")
        print("\nAvailable users:")
        conn = auth_db.get_db()
        users = conn.execute("SELECT id, username, full_name FROM users ORDER BY username").fetchall()
        for user in users:
            print(f"  - {user['username']} (ID: {user['id']}) - {user['full_name']}")
        conn.close()
        sys.exit(1)
    
    target_user_id = target_user['id']
    
    # Confirm transfer
    print(f"\n⚠️  DATA TRANSFER CONFIRMATION")
    print(f"Source User: {source_user['username']} (ID: {source_user_id})")
    print(f"Target User: {target_user['username']} (ID: {target_user_id})")
    print(f"\nThis will copy ALL data from {source_user['username']} to {target_user['username']}")
    print(f"Any existing data in {target_user['username']}'s database will be overwritten.")
    
    confirm = input("\nDo you want to proceed? (yes/no): ").strip().lower()
    
    if confirm != 'yes':
        print("❌ Transfer cancelled")
        sys.exit(0)
    
    # Perform transfer
    success = transfer_data(source_user_id, target_user_id)
    
    if success:
        print(f"\n✨ Data successfully transferred to {target_user['username']}")
    else:
        print(f"\n❌ Transfer failed")
        sys.exit(1)
