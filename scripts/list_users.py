import os
import sys

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_db

auth_db.init_db()
conn = auth_db.get_db()
users = conn.execute('SELECT id, username, full_name, role FROM users ORDER BY username').fetchall()
print("\n=== Users in System ===")
for u in users:
    print(f"ID: {u['id']:3} | Username: {u['username']:15} | Name: {u['full_name']:20} | Role: {u['role']}")
conn.close()
