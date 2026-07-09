import os
import sys
import re

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_db
from db_engine import clean_database_url

def main():
    target_url = os.environ.get('DATABASE_URL')
    if not target_url:
        target_url = input("Enter your PostgreSQL connection string (DATABASE_URL): ").strip()
        
    if not target_url:
        print("Error: DATABASE_URL is required.")
        return

    # Clean and set URL
    target_url = clean_database_url(target_url)
    os.environ['DATABASE_URL'] = target_url
    
    # Re-initialize the db_engine with the target URL
    import db_engine
    db_engine.DATABASE_URL = target_url
    from sqlalchemy import create_engine
    db_engine.engine = create_engine(target_url, pool_recycle=300)

    username = input("Enter the username to reset password for: ").strip()
    if not username:
        print("Error: Username is required.")
        return

    user = auth_db.get_user_by_username_or_email(username)
    if not user:
        print(f"Error: User '{username}' not found in the database.")
        return

    new_password = input("Enter the new password (min 12 chars, upper/lower/number/special): ").strip()
    if not new_password:
        print("Error: New password cannot be empty.")
        return

    # Validate password using project's policy
    valid, msg = auth_db.validate_password(new_password)
    if not valid:
        print(f"Error: Password validation failed - {msg}")
        return

    auth_db.update_password(user['id'], new_password)
    print(f"\n🎉 Password for '{username}' has been successfully updated in PostgreSQL!")

if __name__ == '__main__':
    main()
