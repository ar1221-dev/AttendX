import os
import re
import sqlite3
import urllib.parse
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

try:
    from flask import has_app_context, g
except ImportError:
    has_app_context = lambda: False
    g = None

def clean_database_url(url):
    if not url:
        return url
    
    # Check if it is a postgres URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    if not url.startswith("postgresql://"):
        return url
        
    try:
        # Split scheme
        scheme, rest = url.split("://", 1)
        # Split authority and path/options
        if "/" in rest:
            authority, path = rest.split("/", 1)
        else:
            authority, path = rest, ""
            
        # Split credentials and host
        if "@" in authority:
            credentials, host = authority.rsplit("@", 1)
        else:
            credentials, host = "", authority
            
        if credentials:
            if ":" in credentials:
                username, password = credentials.split(":", 1)
            else:
                username, password = credentials, ""
                
            # Clean password: strip square brackets if they enclose the password
            if password.startswith("[") and password.endswith("]"):
                password = password[1:-1]
                print("Warning: Detected and stripped square brackets '[ ]' around password in DATABASE_URL.")
                
            # URL encode username and password safely
            username = urllib.parse.quote(urllib.parse.unquote(username))
            password = urllib.parse.quote(urllib.parse.unquote(password))
            
            # Reconstruct credentials
            credentials = f"{username}:{password}" if password else username
            authority = f"{credentials}@{host}"
            
        # Reconstruct URL
        return f"{scheme}://{authority}/{path}"
    except Exception as e:
        # Fallback to original URL if anything goes wrong during parsing
        print(f"Warning: Failed to parse/clean DATABASE_URL: {e}")
        return url

# Determine database URL from environment
DB_PATH = None
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASE_URL = clean_database_url(DATABASE_URL)
    # Enable connection pooling with robust limits
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=300
    )
else:
    # Fallback to local SQLite database in DB_DIR or current file dir
    DB_DIR = os.environ.get('DATABASE_DIR', os.path.dirname(__file__))
    DB_PATH = os.path.join(DB_DIR, 'attendance.db')
    engine = create_engine(f'sqlite:///{DB_PATH}', pool_recycle=300)

# Enforce foreign key constraints for SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

def init_tables():
    from models import Base
    Base.metadata.create_all(engine)
    
    # Align sequences if using PostgreSQL
    if engine.dialect.name == 'postgresql':
        tables = [
            'users', 'invitations', 'password_resets', 'semesters', 'subjects',
            'timetable_versions', 'timetable_entries', 'attendance', 'holidays',
            'no_class_days', 'backup_history', 'cancelled_classes', 'extra_class_days'
        ]
        with engine.connect() as conn:
            with conn.begin():
                for table in tables:
                    try:
                        # Check if table exists
                        res = conn.execute(text(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{table}');"))
                        exists = res.scalar()
                        if exists:
                            # Find the sequence name for the 'id' column
                            seq_res = conn.execute(text(f"SELECT pg_get_serial_sequence('\"{table}\"', 'id');"))
                            seq_name = seq_res.scalar()
                            if seq_name:
                                # Update sequence to max(id)
                                conn.execute(text(f"""
                                    SELECT setval('{seq_name}', 
                                           COALESCE((SELECT MAX(id) FROM "{table}"), 1), 
                                           EXISTS (SELECT 1 FROM "{table}"));
                                """))
                    except Exception as e:
                        print(f"Warning: Failed to align sequence for table {table}: {e}")
                        
    # Create indexes for foreign keys and filter columns to avoid full table scans
    indexes = [
        ("idx_semesters_user_id", "semesters", "user_id"),
        ("idx_subjects_semester_id", "subjects", "semester_id"),
        ("idx_timetable_versions_semester_id", "timetable_versions", "semester_id"),
        ("idx_timetable_entries_version_id", "timetable_entries", "version_id"),
        ("idx_attendance_semester_id", "attendance", "semester_id"),
        ("idx_attendance_subject_id", "attendance", "subject_id"),
        ("idx_attendance_date", "attendance", "date"),
        ("idx_holidays_semester_id", "holidays", "semester_id"),
        ("idx_no_class_days_semester_id", "no_class_days", "semester_id"),
        ("idx_cancelled_classes_semester_id", "cancelled_classes", "semester_id"),
        ("idx_extra_class_days_semester_id", "extra_class_days", "semester_id"),
    ]
    try:
        with engine.connect() as conn:
            with conn.begin():
                for idx_name, table, col in indexes:
                    try:
                        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{col}");'))
                    except Exception as e:
                        print(f"Warning: Failed to create index {idx_name} on {table}({col}): {e}")
    except Exception as e:
        print(f"Warning: Connection failed during index creation: {e}")

# User Session Context for Data Isolation
_ACTIVE_USER_ID = None

def set_active_user(user_id):
    global _ACTIVE_USER_ID
    if user_id is not None:
        _ACTIVE_USER_ID = int(user_id)
    else:
        _ACTIVE_USER_ID = None

def rewrite_query(sql, params):
    global _ACTIVE_USER_ID
    
    # Strip trailing semicolon and whitespace to prevent SQL syntax errors during query rewriting
    sql = sql.strip()
    if sql.endswith(';'):
        sql = sql[:-1].strip()

    if _ACTIVE_USER_ID is None:
        return sql, params

    sql_upper = sql.upper()

    # User-owned tables that require data isolation
    user_tables = {
        'semesters', 'subjects', 'timetable_versions', 'timetable_entries',
        'attendance', 'holidays', 'no_class_days', 'settings',
        'backup_history', 'cancelled_classes', 'extra_class_days'
    }

    # Find if any user-owned table is in the query
    target_table = None
    for t in user_tables:
        if re.search(r'\b' + re.escape(t) + r'\b', sql, re.IGNORECASE):
            target_table = t
            break

    if not target_table:
        return sql, params

    # Handle INSERT queries
    if sql_upper.startswith('INSERT'):
        match = re.match(r'^(INSERT(?:\s+OR\s+\w+)?\s+INTO\s+(\w+)\s*\()([^)]+)(\)\s*VALUES\s*\()([^)]+)(\))', sql, re.IGNORECASE)
        if match:
            prefix, table, cols, middle, vals, suffix = match.groups()
            # Only skip if user_id is already in the columns list
            if 'user_id' in [c.strip().lower() for c in cols.split(',')]:
                return sql, params
            new_cols = 'user_id, ' + cols
            new_vals = '?, ' + vals
            new_sql = f"{prefix}{new_cols}{middle}{new_vals}{suffix}"
            new_params = (_ACTIVE_USER_ID,) + tuple(params or ())
            return new_sql, new_params
        return sql, params

    if 'user_id' in sql.lower():
        # Already contains user_id filter, skip rewrite
        return sql, params

    # Handle SELECT, UPDATE, DELETE queries
    # Find table/alias prefix for scoping
    from_match = re.search(r'\b(?:FROM|UPDATE)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?', sql, re.IGNORECASE)
    prefix_col = target_table
    if from_match:
        table_name = from_match.group(1)
        alias_name = from_match.group(2)
        keywords = {'join', 'inner', 'left', 'where', 'on', 'order', 'group', 'limit', 'set'}
        if alias_name and alias_name.lower() not in keywords:
            prefix_col = alias_name
        else:
            prefix_col = table_name

    # Separate GROUP BY, ORDER BY, LIMIT suffix
    suffix_pattern = r'(\b(?:GROUP\s+BY|ORDER\s+BY|LIMIT)\b.*)'
    match_suffix = re.search(suffix_pattern, sql, re.IGNORECASE)
    if match_suffix:
        suffix = match_suffix.group(1)
        main_part = sql[:match_suffix.start()]
    else:
        suffix = ""
        main_part = sql

    where_match = re.search(r'\bWHERE\b', main_part, re.IGNORECASE)
    if where_match:
        # Append AND user_id filter
        main_placeholder_count = main_part.count('?')
        new_params = list(params or ())
        new_params.insert(main_placeholder_count, _ACTIVE_USER_ID)
        main_part += f" AND {prefix_col}.user_id = ? "
        new_sql = main_part + suffix
        return new_sql, tuple(new_params)
    else:
        # Create WHERE user_id filter
        main_placeholder_count = main_part.count('?')
        new_params = list(params or ())
        new_params.insert(main_placeholder_count, _ACTIVE_USER_ID)
        main_part += f" WHERE {prefix_col}.user_id = ? "
        new_sql = main_part + suffix
        return new_sql, tuple(new_params)

class RowWrapper:
    def __init__(self, mapping):
        self._mapping = dict(mapping) if mapping else {}
        self._values = list(self._mapping.values())
        self._keys = list(self._mapping.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def keys(self):
        return self._keys

    def get(self, key, default=None):
        if isinstance(key, int):
            if 0 <= key < len(self._values):
                return self._values[key]
            return default
        return self._mapping.get(key, default)

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def __repr__(self):
        return repr(self._mapping)

class SQLiteCompatibleCursor:
    def __init__(self, result, is_postgres_insert=False):
        self.result = result
        self.is_postgres_insert = is_postgres_insert
        self._lastrowid = None
        self.iterator = None

        if self.is_postgres_insert:
            try:
                row = self.result.fetchone()
                if row:
                    self._lastrowid = row[0]
            except Exception:
                pass

    @property
    def lastrowid(self):
        if self.is_postgres_insert:
            return self._lastrowid
        try:
            return self.result.context.cursor.lastrowid
        except Exception:
            return None

    def fetchone(self):
        try:
            row = self.result.fetchone()
            if row is None:
                return None
            return RowWrapper(row._mapping)
        except Exception:
            return None

    def fetchall(self):
        try:
            rows = self.result.fetchall()
            return [RowWrapper(r._mapping) for r in rows]
        except Exception:
            return []

    def __iter__(self):
        self.iterator = iter(self.result)
        return self

    def __next__(self):
        if self.iterator is None:
            self.iterator = iter(self.result)
        row = next(self.iterator)
        return RowWrapper(row._mapping)

class SQLAlchemyConnectionWrapper:
    def __init__(self, connection, is_request_scoped=False):
        self.connection = connection
        self.transaction = self.connection.begin()
        self.is_request_scoped = is_request_scoped

    def execute(self, sql, params=None):
        sql, params = rewrite_query(sql, params)

        is_postgres = (engine.dialect.name == 'postgresql')
        is_insert = sql.strip().upper().startswith('INSERT')

        if is_postgres:
            if '?' in sql:
                sql = sql.replace('?', '%s')
            if 'INSERT OR IGNORE' in sql.upper():
                sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\b', 'INSERT', sql, flags=re.IGNORECASE)
                sql = sql.strip()
                if sql.endswith(';'):
                    sql = sql[:-1].strip()
                sql += ' ON CONFLICT DO NOTHING'
            elif 'INSERT OR REPLACE' in sql.upper():
                table_match = re.search(r'\bINTO\s+(\w+)\b', sql, re.IGNORECASE)
                if table_match:
                    table_name = table_match.group(1).lower()
                    sql = re.sub(r'\bINSERT\s+OR\s+REPLACE\b', 'INSERT', sql, flags=re.IGNORECASE)
                    sql = sql.strip()
                    if sql.endswith(';'):
                        sql = sql[:-1].strip()
                    
                    if table_name == 'settings':
                        sql += ' ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value'
                    elif table_name == 'holidays':
                        sql += ' ON CONFLICT (user_id, semester_id, date) DO UPDATE SET reason = EXCLUDED.reason'
                    elif table_name == 'no_class_days':
                        sql += ' ON CONFLICT (user_id, semester_id, date) DO UPDATE SET reason = EXCLUDED.reason, custom_description = EXCLUDED.custom_description'
            if is_insert and 'RETURNING' not in sql.upper() and 'SETTINGS' not in sql.upper():
                sql += ' RETURNING id'

        result = self.connection.exec_driver_sql(sql, params or ())
        return SQLiteCompatibleCursor(result, is_postgres_insert=(is_postgres and is_insert and 'SETTINGS' not in sql.upper()))

    def cursor(self):
        return self

    def commit(self):
        if self.transaction:
            self.transaction.commit()
            self.transaction = self.connection.begin()

    def rollback(self):
        if self.transaction:
            self.transaction.rollback()
            self.transaction = self.connection.begin()

    def close(self):
        if self.is_request_scoped:
            if self.transaction:
                try:
                    self.transaction.commit()
                except Exception:
                    pass
                self.transaction = self.connection.begin()
            return

        if self.transaction:
            try:
                self.transaction.commit()
            except Exception:
                pass
        self.connection.close()

    def real_close(self):
        if self.transaction:
            try:
                self.transaction.commit()
            except Exception:
                pass
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        self.close()

def get_connection():
    if has_app_context() and g is not None:
        if '_database_connection' not in g:
            conn = engine.connect()
            g._database_connection = SQLAlchemyConnectionWrapper(conn, is_request_scoped=True)
        return g._database_connection
    else:
        conn = engine.connect()
        return SQLAlchemyConnectionWrapper(conn, is_request_scoped=False)
