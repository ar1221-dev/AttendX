import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models
from models import Base

def migrate():
    # 1. Get Target PostgreSQL Database URL
    target_url = os.environ.get('TARGET_DATABASE_URL')
    if not target_url:
        target_url = input("Enter your target PostgreSQL connection string (DATABASE_URL): ").strip()
        
    if not target_url:
        print("Error: TARGET_DATABASE_URL is required.")
        return

    # Clean and parse the target PostgreSQL URL
    from db_engine import clean_database_url
    target_url = clean_database_url(target_url)

    print("\nConnecting to local SQLite database...")
    local_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'attendance.db')
    if not os.path.exists(local_db_path):
        print(f"Error: Local SQLite database not found at {local_db_path}")
        return

    sqlite_engine = create_engine(f"sqlite:///{local_db_path}")
    SqliteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SqliteSession()

    print("Connecting to target PostgreSQL database...")
    try:
        pg_engine = create_engine(target_url)
        PgSession = sessionmaker(bind=pg_engine)
        pg_session = PgSession()
        
        # Test connection
        pg_engine.connect()
    except Exception as e:
        print(f"Error: Could not connect to PostgreSQL: {e}")
        return

    print("Creating tables in PostgreSQL database...")
    Base.metadata.create_all(pg_engine)

    # Tables in correct dependency order
    tables = [
        models.User,
        models.Invitation,
        models.PasswordReset,
        models.Semester,
        models.Subject,
        models.TimetableVersion,
        models.TimetableEntry,
        models.Attendance,
        models.Holiday,
        models.NoClassDay,
        models.Setting,
        models.BackupHistory,
        models.CancelledClass,
        models.ExtraClassDay
    ]

    try:
        for model in tables:
            table_name = model.__tablename__
            print(f"Migrating table {table_name}...")
            
            # Fetch all records from SQLite
            records = sqlite_session.query(model).all()
            print(f"  Found {len(records)} records in SQLite.")
            
            # Transfer to PG
            for record in records:
                attrs = {col.name: getattr(record, col.name) for col in model.__table__.columns}
                new_record = model(**attrs)
                pg_session.merge(new_record)
                
            pg_session.commit()
            print(f"  Successfully migrated {table_name}.")
            
        print("\n🎉 Migration completed successfully!")
    except Exception as e:
        pg_session.rollback()
        print(f"\n❌ Error during migration: {e}")
    finally:
        sqlite_session.close()
        pg_session.close()

if __name__ == '__main__':
    migrate()
