import sqlite3
import os
import sys

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if main database exists
main_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'attendance.db')
if os.path.exists(main_db_path):
    print("\n=== Main Database (attendance.db) ===")
    conn = sqlite3.connect(main_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Found {len(tables)} tables")
    
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"  - {table_name}: {count} records")
    conn.close()
else:
    print("No main attendance.db found")

# Check user databases
import database as db
for user_id in [1, 2]:
    db_path = db.get_user_db_path(user_id)
    if os.path.exists(db_path):
        user = "admin" if user_id == 1 else "Raj"
        print(f"\n=== User Database: {user} (ID: {user_id}) ===")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"  - {table_name}: {count} records")
        conn.close()
