import os
from datetime import datetime, timedelta, date
import db_engine

_ACTIVE_USER_ID = None
DB_PATH = db_engine.DB_PATH


def set_active_user(user_id):
    global _ACTIVE_USER_ID
    if user_id is not None:
        _ACTIVE_USER_ID = int(user_id)
    else:
        _ACTIVE_USER_ID = None
    db_engine.set_active_user(_ACTIVE_USER_ID)


def clear_active_user():
    set_active_user(None)


def get_db(user_id=None):
    return db_engine.get_connection()


def init_db(user_id=None):
    db_engine.init_tables()
    
    if user_id is None:
        user_id = _ACTIVE_USER_ID
        
    if user_id:
        old_active_user = _ACTIVE_USER_ID
        set_active_user(user_id)
        try:
            conn = get_db()
            cursor = conn.cursor()
            default_settings = {
                'theme': 'dark',
                'default_target': '75',
                'first_day_of_week': '1', # 1 = Monday
                'date_format': '%Y-%m-%d',
                'time_format': '%H:%M',
                'auto_backup': 'true',
                'custom_goals': '75,80,85,90'
            }
            for key, val in default_settings.items():
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);", (key, val))
            conn.commit()
            conn.close()
        finally:
            set_active_user(old_active_user)


def ensure_user_db(user_id):
    if not user_id:
        return
    init_db(user_id)


def _run_migrations(conn):
    """Apply schema migrations for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(semesters);").fetchall()}
    if 'working_days' not in cols:
        conn.execute("ALTER TABLE semesters ADD COLUMN working_days TEXT DEFAULT '0,1,2,3,4';")
    
    v_cols = {row[1] for row in conn.execute("PRAGMA table_info(timetable_versions);").fetchall()}
    if 'end_date' not in v_cols:
        conn.execute("ALTER TABLE timetable_versions ADD COLUMN end_date DATE;")
    conn.commit()

# --- Semesters ---
def get_semesters():
    conn = get_db()
    semesters = conn.execute("SELECT * FROM semesters ORDER BY start_date DESC;").fetchall()
    conn.close()
    return semesters

def get_semester(semester_id):
    conn = get_db()
    semester = conn.execute("SELECT * FROM semesters WHERE id = ?;", (semester_id,)).fetchone()
    conn.close()
    return semester

def add_semester(name, start_date=None, end_date=None, target=75.0, notes='', working_days='0,1,2,3,4'):
    if not start_date:
        start_date = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO semesters (name, start_date, end_date, target, working_days, notes) VALUES (?, ?, ?, ?, ?, ?);",
        (name, start_date, end_date or None, target, working_days, notes)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def update_semester(semester_id, name, start_date, end_date, target, notes, working_days='0,1,2,3,4'):
    conn = get_db()
    conn.execute(
        "UPDATE semesters SET name = ?, start_date = ?, end_date = ?, target = ?, working_days = ?, notes = ? WHERE id = ?;",
        (name, start_date, end_date or None, target, working_days, notes, semester_id)
    )
    conn.commit()
    conn.close()

def delete_semester(semester_id):
    conn = get_db()
    conn.execute("DELETE FROM semesters WHERE id = ?;", (semester_id,))
    conn.commit()
    conn.close()

# --- Subjects ---
def get_subjects(semester_id):
    conn = get_db()
    subjects = conn.execute("SELECT * FROM subjects WHERE semester_id = ? ORDER BY name ASC;", (semester_id,)).fetchall()
    conn.close()
    return subjects

def get_subject(subject_id):
    conn = get_db()
    subject = conn.execute("SELECT * FROM subjects WHERE id = ?;", (subject_id,)).fetchone()
    conn.close()
    return subject

def add_subject(semester_id, name, code, faculty, credits):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO subjects (semester_id, name, code, faculty, credits) VALUES (?, ?, ?, ?, ?);",
        (semester_id, name, code, faculty, credits)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def update_subject(subject_id, name, code, faculty, credits):
    conn = get_db()
    conn.execute(
        "UPDATE subjects SET name = ?, code = ?, faculty = ?, credits = ? WHERE id = ?;",
        (name, code, faculty, credits, subject_id)
    )
    conn.commit()
    conn.close()

def delete_subject(subject_id):
    conn = get_db()
    conn.execute("DELETE FROM subjects WHERE id = ?;", (subject_id,))
    conn.commit()
    conn.close()

# --- Timetable Versions & Entries ---
def get_timetable_versions(semester_id):
    conn = get_db()
    versions = conn.execute("SELECT * FROM timetable_versions WHERE semester_id = ? ORDER BY effective_date DESC;", (semester_id,)).fetchall()
    conn.close()
    return versions

def add_timetable_version(semester_id, version_name, effective_date, end_date=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO timetable_versions (semester_id, version_name, effective_date, end_date) VALUES (?, ?, ?, ?);",
        (semester_id, version_name, effective_date, end_date or None)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def delete_timetable_version(version_id):
    conn = get_db()
    conn.execute("DELETE FROM timetable_versions WHERE id = ?;", (version_id,))
    conn.commit()
    conn.close()

def add_timetable_entry(version_id, subject_id, day_of_week, start_time, end_time, room, notes):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO timetable_entries (version_id, subject_id, day_of_week, start_time, end_time, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?);",
        (version_id, subject_id, day_of_week, start_time, end_time, room, notes)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def parse_time_sort_key(time_str):
    """Sort key helper to order class times chronologically (handling 12h/24h boundaries like 9am to 4pm)."""
    try:
        h, m = map(int, time_str.split(':')[:2])
        if 1 <= h <= 8:
            h += 12
        return (h, m)
    except Exception:
        return (0, 0)

def get_timetable_entries(version_id):
    conn = get_db()
    entries = conn.execute("""
        SELECT e.*, s.name as subject_name, s.code as subject_code, s.faculty as subject_faculty
        FROM timetable_entries e
        JOIN subjects s ON e.subject_id = s.id
        WHERE e.version_id = ?;
    """, (version_id,)).fetchall()
    conn.close()
    
    entries_list = [dict(row) for row in entries]
    entries_list.sort(key=lambda x: (x['day_of_week'], parse_time_sort_key(x['start_time'])))
    return entries_list

def update_timetable_entry(entry_id, subject_id, day_of_week, start_time, end_time, room, notes):
    conn = get_db()
    conn.execute(
        "UPDATE timetable_entries SET subject_id = ?, day_of_week = ?, start_time = ?, end_time = ?, room = ?, notes = ? WHERE id = ?;",
        (subject_id, day_of_week, start_time, end_time, room, notes, entry_id)
    )
    conn.commit()
    conn.close()

def clear_timetable_entries(version_id):
    conn = get_db()
    conn.execute("DELETE FROM timetable_entries WHERE version_id = ?;", (version_id,))
    conn.commit()
    conn.close()

# Resolve timetable version for a given date
def resolve_timetable_version(semester_id, target_date_str):
    conn = get_db()
    # Find active version: effective_date <= target_date AND (end_date IS NULL OR target_date <= end_date)
    version = conn.execute("""
        SELECT * FROM timetable_versions
        WHERE semester_id = ? AND effective_date <= ? AND (end_date IS NULL OR ? <= end_date)
        ORDER BY effective_date DESC
        LIMIT 1;
    """, (semester_id, target_date_str, target_date_str)).fetchone()
    
    conn.close()
    return version

# --- Attendance ---
def get_attendance_for_date(semester_id, date_str):
    conn = get_db()
    records = conn.execute("""
        SELECT a.*, s.name as subject_name
        FROM attendance a
        JOIN subjects s ON a.subject_id = s.id
        WHERE a.semester_id = ? AND a.date = ?;
    """, (semester_id, date_str)).fetchall()
    conn.close()
    return {f"{r['subject_id']}_{r['time']}": r for r in records}

def mark_attendance(semester_id, subject_id, date_str, time_str, status, version_id, notes=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attendance (semester_id, subject_id, date, time, status, version_id, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, subject_id, date, time) DO UPDATE SET
            status = excluded.status,
            version_id = excluded.version_id,
            notes = excluded.notes;
    """, (semester_id, subject_id, date_str, time_str, status, version_id, notes))
    conn.commit()
    conn.close()

def delete_attendance(attendance_id):
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE id = ?;", (attendance_id,))
    conn.commit()
    conn.close()

def sync_attendance_from_timetable(semester_id, up_to_date=None):
    """
    Auto-generate attendance records from the timetable for each working day
    from semester start through up_to_date (default: today).
    Existing records are preserved. Holidays and no-class days are marked as
    missed so the missed-class counts update correctly, while non-holiday days
    default to 'attended'.
    """
    semester = get_semester(semester_id)
    if not semester:
        return {'created': 0, 'skipped_days': 0}

    start_date = datetime.strptime(semester['start_date'], '%Y-%m-%d').date()
    end_date = up_to_date or date.today()
    if end_date < start_date:
        return {'created': 0, 'skipped_days': 0}

    conn = get_db()
    
    holidays = {h['date'] for h in conn.execute(
        "SELECT date FROM holidays WHERE semester_id = ?;", (semester_id,)
    ).fetchall()}
    no_classes = {n['date'] for n in conn.execute(
        "SELECT date FROM no_class_days WHERE semester_id = ?;", (semester_id,)
    ).fetchall()}
    
    cancelled_classes = {} # date_str -> set of subject_ids
    for c in conn.execute("SELECT date, subject_id FROM cancelled_classes WHERE semester_id = ?;", (semester_id,)).fetchall():
        cancelled_classes.setdefault(c['date'], set()).add(c['subject_id'])
        
    extra_class_days = {} # date_str -> day_to_follow
    for e in conn.execute("SELECT date, day_to_follow FROM extra_class_days WHERE semester_id = ?;", (semester_id,)).fetchall():
        extra_class_days[e['date']] = e['day_to_follow']

    versions = conn.execute(
        "SELECT * FROM timetable_versions WHERE semester_id = ? ORDER BY effective_date DESC;",
        (semester_id,)
    ).fetchall()
    version_entries = {}
    for v in versions:
        version_entries[v['id']] = conn.execute(
            "SELECT * FROM timetable_entries WHERE version_id = ?;", (v['id'],)
        ).fetchall()

    if not versions:
        conn.close()
        return {'created': 0, 'skipped_days': 0}

    # Fetch all existing attendance records for the semester to process in-memory
    existing_attendance = conn.execute(
        "SELECT id, subject_id, date, time, version_id, notes, status FROM attendance WHERE semester_id = ?;",
        (semester_id,)
    ).fetchall()
    
    attendance_by_date = {}
    for att in existing_attendance:
        attendance_by_date.setdefault(att['date'], []).append(att)

    # In-memory version resolver to eliminate O(N) database queries
    def resolve_version_in_memory(target_date_str):
        for v in versions:
            eff = v['effective_date']
            end = v.get('end_date')
            if eff <= target_date_str and (end is None or target_date_str <= end):
                return v
        return None

    created = 0
    skipped_days = 0
    curr = start_date

    while curr <= end_date:
        d_str = curr.strftime('%Y-%m-%d')
        is_special_day = d_str in holidays or d_str in no_classes
        if is_special_day:
            conn.execute(
                "DELETE FROM attendance WHERE semester_id = ? AND date = ?;",
                (semester_id, d_str)
            )
            active_version = resolve_version_in_memory(d_str)
            if active_version:
                entries = version_entries.get(active_version['id'], [])
                weekday = extra_class_days.get(d_str, curr.weekday())
                cancelled_subs = cancelled_classes.get(d_str, set())
                day_entries = [e for e in entries if e['day_of_week'] == weekday and e['subject_id'] not in cancelled_subs]
                for entry in day_entries:
                    conn.execute("""
                        INSERT INTO attendance (semester_id, subject_id, date, time, status, version_id, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, subject_id, date, time) DO UPDATE SET
                            status = excluded.status,
                            version_id = excluded.version_id,
                            notes = excluded.notes;
                    """, (semester_id, entry['subject_id'], d_str, entry['start_time'], 'missed', active_version['id'], 'Holiday/No-class day'))
            skipped_days += 1
            curr += timedelta(days=1)
            continue

        active_version = resolve_version_in_memory(d_str)
        if not active_version:
            conn.execute("""
                DELETE FROM attendance 
                WHERE semester_id = ? AND date = ? AND (notes IS NULL OR notes = '' OR notes = 'Holiday/No-class day');
            """, (semester_id, d_str))
            curr += timedelta(days=1)
            continue

        entries = version_entries.get(active_version['id'], [])
        weekday = extra_class_days.get(d_str, curr.weekday())
        cancelled_subs = cancelled_classes.get(d_str, set())
        day_entries = [e for e in entries if e['day_of_week'] == weekday and e['subject_id'] not in cancelled_subs]
        active_keys = {f"{e['subject_id']}_{e['start_time']}" for e in day_entries}

        existing = attendance_by_date.get(d_str, [])
        for row in existing:
            key = f"{row['subject_id']}_{row['time']}"
            if key not in active_keys and (row['notes'] == '' or row['notes'] == 'Holiday/No-class day' or row['notes'] is None):
                conn.execute("DELETE FROM attendance WHERE id = ?;", (row['id'],))
        
        existing_keys = {f"{row['subject_id']}_{row['time']}" for row in existing}
        for entry in day_entries:
            key = f"{entry['subject_id']}_{entry['start_time']}"
            if key not in existing_keys:
                conn.execute("""
                    INSERT INTO attendance (semester_id, subject_id, date, time, status, version_id, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, subject_id, date, time) DO UPDATE SET
                        status = excluded.status,
                        version_id = excluded.version_id,
                        notes = excluded.notes;
                """, (semester_id, entry['subject_id'], d_str, entry['start_time'], 'attended', active_version['id'], ''))
                created += 1

        curr += timedelta(days=1)

    conn.commit()
    conn.close()
    return {'created': created, 'skipped_days': skipped_days}

# --- Holidays & No-Class Days ---
def get_holidays(semester_id):
    conn = get_db()
    holidays = conn.execute("SELECT * FROM holidays WHERE semester_id = ? ORDER BY date ASC;", (semester_id,)).fetchall()
    conn.close()
    return holidays

def add_holiday(semester_id, date_str, reason):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO holidays (semester_id, date, reason) VALUES (?, ?, ?);", (semester_id, date_str, reason))
    conn.commit()
    conn.close()

def delete_holiday(holiday_id):
    conn = get_db()
    conn.execute("DELETE FROM holidays WHERE id = ?;", (holiday_id,))
    conn.commit()
    conn.close()

def get_no_class_days(semester_id):
    conn = get_db()
    records = conn.execute("SELECT * FROM no_class_days WHERE semester_id = ? ORDER BY date ASC;", (semester_id,)).fetchall()
    conn.close()
    return records

def add_no_class_day(semester_id, date_str, reason, desc=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO no_class_days (semester_id, date, reason, custom_description) VALUES (?, ?, ?, ?);",
        (semester_id, date_str, reason, desc)
    )
    conn.commit()
    conn.close()

def delete_no_class_day(no_class_day_id):
    conn = get_db()
    conn.execute("DELETE FROM no_class_days WHERE id = ?;", (no_class_day_id,))
    conn.commit()
    conn.close()

# Check if a date is a holiday or a no-class day
def get_special_day_status(semester_id, date_str):
    conn = get_db()
    holiday = conn.execute("SELECT * FROM holidays WHERE semester_id = ? AND date = ?;", (semester_id, date_str)).fetchone()
    if holiday:
        conn.close()
        return {'type': 'holiday', 'reason': holiday['reason']}
    
    no_class = conn.execute("SELECT * FROM no_class_days WHERE semester_id = ? AND date = ?;", (semester_id, date_str)).fetchone()
    if no_class:
        conn.close()
        return {'type': 'no_class', 'reason': no_class['reason'], 'desc': no_class['custom_description']}
    
    conn.close()
    return None

def _count_classes_on_date(semester_id, date_str):
    """Count scheduled classes on a date (ignoring whether it's a leave day)."""
    dt = datetime.strptime(date_str, '%Y-%m-%d').date()
    version = resolve_timetable_version(semester_id, date_str)
    if not version:
        return 0
    entries = get_timetable_entries(version['id'])
    return len([e for e in entries if e['day_of_week'] == dt.weekday()])


def get_leave_summary(semester_id):
    """Summarize recorded leaves/holidays and their effect on attendance."""
    holidays = get_holidays(semester_id)
    no_class_days = get_no_class_days(semester_id)
    details = []
    excluded_classes = 0

    for h in holidays:
        count = _count_classes_on_date(semester_id, h['date'])
        excluded_classes += count
        details.append({
            'date': h['date'],
            'reason': h['reason'],
            'type': 'holiday',
            'type_label': 'Leave / Holiday',
            'classes_excluded': count,
        })

    for n in no_class_days:
        count = _count_classes_on_date(semester_id, n['date'])
        excluded_classes += count
        details.append({
            'date': n['date'],
            'reason': n['reason'].replace('_', ' ').title(),
            'type': 'no_class',
            'type_label': 'No-Class Day',
            'classes_excluded': count,
            'description': n['custom_description'] or '',
        })

    details.sort(key=lambda x: x['date'])
    return {
        'total_days': len(holidays) + len(no_class_days),
        'holiday_count': len(holidays),
        'no_class_count': len(no_class_days),
        'excluded_classes': excluded_classes,
        'details': details,
    }


def import_leaves_from_rows(semester_id, rows):
    """Import leave/holiday rows. Returns count imported."""
    imported = 0
    for r in rows:
        date_str = ''
        reason = 'Leave'
        for key, val in r.items():
            if not val:
                continue
            kl = key.lower().strip()
            if kl in ('date', 'leave date', 'holiday date', 'day', 'leave day'):
                date_str = str(val).strip()[:10]
            elif kl in ('reason', 'leave', 'holiday', 'name', 'description', 'type', 'remarks'):
                reason = str(val).strip() or 'Leave'

        if not date_str:
            continue
        # Normalize date — handle DD-MM-YYYY
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                date_str = datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
                break
            except ValueError:
                continue

        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            continue

        add_holiday(semester_id, date_str, reason)
        imported += 1

    if imported:
        sync_attendance_from_timetable(semester_id)
    return imported

# --- Core Calculations & Stats ---
def calculate_attendance_stats(semester_id):
    conn = get_db()
    subjects = conn.execute("SELECT * FROM subjects WHERE semester_id = ?;", (semester_id,)).fetchall()
    
    subject_stats = {}
    total_attended = 0
    total_missed = 0
    today_str = date.today().strftime('%Y-%m-%d')
    
    for sub in subjects:
        sub_id = sub['id']
        att_row = conn.execute("""
            SELECT 
                SUM(CASE WHEN status = 'attended' THEN 1 ELSE 0 END) as attended,
                SUM(CASE WHEN status = 'missed' THEN 1 ELSE 0 END) as missed
            FROM attendance
            WHERE subject_id = ? AND date < ?;
        """, (sub_id, today_str)).fetchone()
        
        attended = att_row['attended'] or 0
        missed = att_row['missed'] or 0
        total = attended + missed
        percentage = (attended / total * 100) if total > 0 else 100.0
        
        subject_stats[sub_id] = {
            'id': sub_id,
            'name': sub['name'],
            'code': sub['code'],
            'faculty': sub['faculty'],
            'credits': sub['credits'],
            'attended': attended,
            'missed': missed,
            'total': total,
            'percentage': round(percentage, 2)
        }
        
        total_attended += attended
        total_missed += missed

    overall_conducted = total_attended + total_missed
    overall_percentage = (total_attended / overall_conducted * 100) if overall_conducted > 0 else 100.0
    
    conn.close()
    
    return {
        'subjects': list(subject_stats.values()),
        'overall': {
            'conducted': overall_conducted,
            'attended': total_attended,
            'missed': total_missed,
            'percentage': round(overall_percentage, 2)
        }
    }

# Safe Leaves & Required Classes Calculator
def get_custom_goals():
    goals_str = get_setting('custom_goals', '75,80,85,90')
    try:
        return sorted([int(g.strip()) for g in goals_str.split(',') if g.strip()])
    except ValueError:
        return [75, 80, 85, 90]

def calculate_goals_and_leaves(semester_id, target_percentage=75.0):
    stats = calculate_attendance_stats(semester_id)
    overall = stats['overall']
    custom_targets = get_custom_goals()
    
    att = overall['attended']
    cond = overall['conducted']
    miss = overall['missed']
    
    # Required classes to reach target
    required_classes = {}
    for target in custom_targets:
        t = target / 100.0
        if cond == 0:
            req = 0
        else:
            # Let x = classes to attend consecutively: (att + x) / (cond + x) >= t -> att + x >= t * cond + t * x -> x(1 - t) >= t * cond - att
            # x >= (t * cond - att) / (1 - t)
            if (att / cond) >= t:
                req = 0
            else:
                req = int(((t * cond) - att) / (1 - t)) + (1 if (((t * cond) - att) % (1 - t)) > 0 else 0)
        required_classes[target] = max(0, req)

    # Safe leaves (consecutive classes we can miss before falling below target)
    # (att) / (cond + y) >= target_percentage/100 -> att >= t * cond + t * y -> t * y <= att - t * cond -> y <= (att - t * cond) / t
    t = target_percentage / 100.0
    if cond == 0:
        safe_leaves = 0
    else:
        if (att / cond) < t:
            safe_leaves = 0
        else:
            safe_leaves = int((att - (t * cond)) / t)

    # Subject-wise safe leaves/required
    subject_goals = []
    for sub in stats['subjects']:
        sub_att = sub['attended']
        sub_cond = sub['total']
        
        # Subject-wise Safe Leaves
        if sub_cond == 0:
            sub_safe = 0
            sub_req = 0
        else:
            # Safe leaves
            if (sub_att / sub_cond) < t:
                sub_safe = 0
            else:
                sub_safe = int((sub_att - (t * sub_cond)) / t)
            
            # Required classes
            if (sub_att / sub_cond) >= t:
                sub_req = 0
            else:
                sub_req = int(((t * sub_cond) - sub_att) / (1 - t)) + (1 if (((t * sub_cond) - sub_att) % (1 - t)) > 0 else 0)
                
        subject_goals.append({
            'subject_id': sub['id'],
            'name': sub['name'],
            'code': sub['code'],
            'percentage': sub['percentage'],
            'safe_leaves': sub_safe,
            'required': sub_req
        })

    return {
        'required': required_classes,
        'safe_leaves': safe_leaves,
        'subject_goals': subject_goals
    }

# Calendar events generator
def get_calendar_events(semester_id, year, month):
    conn = get_db()
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
        
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    # Get holidays
    holidays = {h['date']: h['reason'] for h in conn.execute("SELECT * FROM holidays WHERE semester_id = ? AND date BETWEEN ? AND ?;", (semester_id, start_str, end_str)).fetchall()}
    # Get no-class days
    no_classes = {n['date']: n['reason'] for n in conn.execute("SELECT * FROM no_class_days WHERE semester_id = ? AND date BETWEEN ? AND ?;", (semester_id, start_str, end_str)).fetchall()}
    
    # Get marked attendance for these dates
    attendance_records = conn.execute("""
        SELECT date, status, COUNT(*) as count
        FROM attendance
        WHERE semester_id = ? AND date BETWEEN ? AND ?
        GROUP BY date, status;
    """, (semester_id, start_str, end_str)).fetchall()
    
    daily_attendance = {}
    for r in attendance_records:
        d = r['date']
        if d not in daily_attendance:
            daily_attendance[d] = {'attended': 0, 'missed': 0}
        daily_attendance[d][r['status']] = r['count']
        
    events = {}
    curr = start_date
    today = date.today()
    while curr <= end_date:
        d_str = curr.strftime('%Y-%m-%d')
        
        if d_str in holidays:
            events[d_str] = {'status': 'holiday', 'color': 'blue', 'title': f"Holiday: {holidays[d_str]}"}
        elif d_str in no_classes:
            events[d_str] = {'status': 'no_class', 'color': 'grey', 'title': f"No Classes: {no_classes[d_str].replace('_', ' ').capitalize()}"}
        elif d_str in daily_attendance and curr < today:
            att = daily_attendance[d_str]['attended']
            miss = daily_attendance[d_str]['missed']
            if att > 0 and miss == 0:
                events[d_str] = {'status': 'attended', 'color': 'green', 'title': f"Attended ({att}/{att})"}
            elif att == 0 and miss > 0:
                events[d_str] = {'status': 'missed', 'color': 'red', 'title': f"Missed ({miss}/{miss})"}
            else:
                events[d_str] = {'status': 'partial', 'color': 'yellow', 'title': f"Partial ({att}/{att+miss})"}
        else:
            events[d_str] = {'status': 'unmarked', 'color': 'light', 'title': 'No attendance marked'}
            
        curr += timedelta(days=1)
        
    conn.close()
    return events

# --- Settings ---
def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);", (key, str(value)))
    conn.commit()
    conn.close()

# --- Simulator & Predictor Functions ---
def run_attendance_prediction(semester_id, prediction_type, target_date_str=None, param=None):
    """
    prediction_type can be:
    - 'attend_all_remaining': Simulate attending all classes from today to semester end.
    - 'attend_until_date': Simulate attending all classes from today until target_date_str, and optionally miss/attend the rest.
    - 'attend_only_subject_until_date': Simulate attending only specific subject classes until target_date_str.
    - 'miss_every_friday': Simulate missing every Friday class.
    - 'miss_next_n': Simulate missing next N classes from today.
    """
    conn = get_db()
    sem = conn.execute("SELECT * FROM semesters WHERE id = ?;", (semester_id,)).fetchone()
    if not sem:
        conn.close()
        return None
        
    start_date_sem = datetime.strptime(sem['start_date'], '%Y-%m-%d').date()
    if sem['end_date']:
        end_date_sem = datetime.strptime(sem['end_date'], '%Y-%m-%d').date()
    else:
        end_date_sem = start_date_sem + timedelta(days=180) # default 6 months semester duration
    today = date.today()
    
    # Start simulating from today onwards (or semester start if semester hasn't started yet)
    sim_start = max(today, start_date_sem)
    sim_end = end_date_sem
    
    if target_date_str:
        sim_end_target = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        sim_end = min(sim_end, sim_end_target)
        
    # Get existing attendance records (historical)
    history = conn.execute("SELECT subject_id, status FROM attendance WHERE semester_id = ? AND date < ?;", (semester_id, today.strftime('%Y-%m-%d'))).fetchall()
    sub_sim_stats = {}
    subjects = conn.execute("SELECT * FROM subjects WHERE semester_id = ?;", (semester_id,)).fetchall()
    
    for sub in subjects:
        sub_sim_stats[sub['id']] = {
            'id': sub['id'],
            'name': sub['name'],
            'code': sub['code'],
            'attended': 0,
            'missed': 0
        }
        
    # Seed with existing stats
    for record in history:
        sid = record['subject_id']
        if sid in sub_sim_stats:
            if record['status'] == 'attended':
                sub_sim_stats[sid]['attended'] += 1
            else:
                sub_sim_stats[sid]['missed'] += 1
                
    # Get holidays and no-class days
    holidays = {h['date'] for h in conn.execute("SELECT date FROM holidays WHERE semester_id = ? AND date >= ?;", (semester_id, sim_start.strftime('%Y-%m-%d'))).fetchall()}
    no_classes = {n['date'] for n in conn.execute("SELECT date FROM no_class_days WHERE semester_id = ? AND date >= ?;", (semester_id, sim_start.strftime('%Y-%m-%d'))).fetchall()}
    
    cancelled_classes = {}
    for c in conn.execute("SELECT date, subject_id FROM cancelled_classes WHERE semester_id = ? AND date >= ?;", (semester_id, sim_start.strftime('%Y-%m-%d'))).fetchall():
        cancelled_classes.setdefault(c['date'], set()).add(c['subject_id'])
        
    extra_class_days = {}
    for e in conn.execute("SELECT date, day_to_follow FROM extra_class_days WHERE semester_id = ? AND date >= ?;", (semester_id, sim_start.strftime('%Y-%m-%d'))).fetchall():
        extra_class_days[e['date']] = e['day_to_follow']
    
    # We will step day-by-day and simulate the timetable
    curr = sim_start
    missed_counter = 0 # used for 'miss_next_n'
    
    # Pre-load all timetable versions for resolution
    versions = conn.execute("SELECT * FROM timetable_versions WHERE semester_id = ? ORDER BY effective_date DESC;", (semester_id,)).fetchall()
    
    # Map version to entries
    version_entries = {}
    for v in versions:
        version_entries[v['id']] = conn.execute("SELECT * FROM timetable_entries WHERE version_id = ?;", (v['id'],)).fetchall()
        
    while curr <= sim_end:
        curr_str = curr.strftime('%Y-%m-%d')
        
        # Stop early for miss_next_n if we reached N
        if prediction_type == 'miss_next_n' and missed_counter >= int(param):
            break
            
        # Skip if holiday/no-class day
        if curr_str in holidays or curr_str in no_classes:
            curr += timedelta(days=1)
            continue
            
        # Find active version for this day
        active_version = None
        for v in versions:
            if v['effective_date'] <= curr_str:
                active_version = v
                break
        if not active_version and versions:
            active_version = versions[-1] # earliest
            
        if active_version:
            entries = version_entries[active_version['id']]
            day_of_week = extra_class_days.get(curr_str, curr.weekday())
            
            # Find classes scheduled on this day
            cancelled_subs = cancelled_classes.get(curr_str, set())
            scheduled = [e for e in entries if e['day_of_week'] == day_of_week and e['subject_id'] not in cancelled_subs]
            
            for entry in scheduled:
                sub_id = entry['subject_id']
                if sub_id not in sub_sim_stats:
                    continue
                    
                has_att = conn.execute("SELECT 1 FROM attendance WHERE subject_id = ? AND date = ? AND time = ?;", (sub_id, curr_str, entry['start_time'])).fetchone()
                if has_att:
                    continue
                
                # Determine status based on prediction rules
                simulated_status = 'attended'
                
                if prediction_type == 'attend_all_remaining':
                    simulated_status = 'attended'
                elif prediction_type == 'attend_until_date':
                    simulated_status = 'attended'
                elif prediction_type == 'attend_only_subject_until_date':
                    target_sub_id = int(param)
                    if sub_id == target_sub_id:
                        simulated_status = 'attended'
                    else:
                        simulated_status = 'missed'
                elif prediction_type == 'miss_every_friday':
                    if day_of_week == 4: # Friday
                        simulated_status = 'missed'
                    else:
                        simulated_status = 'attended'
                elif prediction_type == 'miss_next_n':
                    n = int(param)
                    if missed_counter < n:
                        simulated_status = 'missed'
                        missed_counter += 1
                    else:
                        # Should not reach here because of the break above, but safe
                        simulated_status = 'attended'
                
                if simulated_status == 'attended':
                    sub_sim_stats[sub_id]['attended'] += 1
                else:
                    sub_sim_stats[sub_id]['missed'] += 1
                    
        curr += timedelta(days=1)
        
    conn.close()
    
    # Calculate final simulated percentages
    total_sim_att = 0
    total_sim_miss = 0
    sim_subjects = []
    
    for sub in sub_sim_stats.values():
        sub_total = sub['attended'] + sub['missed']
        sub['total'] = sub_total
        sub['percentage'] = round((sub['attended'] / sub_total * 100) if sub_total > 0 else 100.0, 2)
        sim_subjects.append(sub)
        total_sim_att += sub['attended']
        total_sim_miss += sub['missed']
        
    total_sim_conducted = total_sim_att + total_sim_miss
    overall_sim_percentage = round((total_sim_att / total_sim_conducted * 100) if total_sim_conducted > 0 else 100.0, 2)
    
    return {
        'subjects': sim_subjects,
        'overall': {
            'conducted': total_sim_conducted,
            'attended': total_sim_att,
            'missed': total_sim_miss,
            'percentage': overall_sim_percentage
        }
    }

def get_semester_date_bounds(semester):
    """Return (start_date, end_date_or_default) for a semester row."""
    start = datetime.strptime(semester['start_date'], '%Y-%m-%d').date()
    if semester['end_date']:
        end = datetime.strptime(semester['end_date'], '%Y-%m-%d').date()
    else:
        end = start + timedelta(days=365)
    return start, end

def get_upcoming_classes(semester_id, days=7):
    """Return scheduled classes for the next N days from today."""
    semester = get_semester(semester_id)
    if not semester:
        return []
    
    today = date.today()
    _, sem_end = get_semester_date_bounds(semester)
    working_days = set()
    if semester['working_days']:
        working_days = {int(d) for d in semester['working_days'].split(',') if d.strip().isdigit()}
    
    upcoming = []
    curr = today
    end_scan = min(today + timedelta(days=days), sem_end)
    
    while curr <= end_scan:
        curr_str = curr.strftime('%Y-%m-%d')
        weekday = curr.weekday()
        
        if working_days and weekday not in working_days:
            curr += timedelta(days=1)
            continue
        
        special = get_special_day_status(semester_id, curr_str)
        if special:
            curr += timedelta(days=1)
            continue
        
        active_version = resolve_timetable_version(semester_id, curr_str)
        if active_version:
            entries = get_timetable_entries(active_version['id'])
            day_entries = [e for e in entries if e['day_of_week'] == weekday]
            marked = get_attendance_for_date(semester_id, curr_str) if curr <= today else {}
            
            for entry in day_entries:
                key = f"{entry['subject_id']}_{entry['start_time']}"
                upcoming.append({
                    'date': curr_str,
                    'date_label': curr.strftime('%a, %b %d'),
                    'is_today': curr == today,
                    'subject_name': entry['subject_name'],
                    'subject_code': entry['subject_code'],
                    'start_time': entry['start_time'],
                    'end_time': entry['end_time'],
                    'room': entry['room'],
                    'faculty': entry['subject_faculty'],
                    'marked': key in marked,
                    'marked_status': marked[key]['status'] if key in marked else None
                })
        curr += timedelta(days=1)
    
    upcoming.sort(key=lambda x: (x['date'], x['start_time']))
    return upcoming[:20]

def get_notifications(semester_id):
    """Generate contextual reminders for the active semester."""
    semester = get_semester(semester_id)
    if not semester:
        return []
    
    notifications = []
    today_str = date.today().strftime('%Y-%m-%d')
    now = datetime.now()
    
    # Today's class reminders
    special = get_special_day_status(semester_id, today_str)
    if not special:
        active_version = resolve_timetable_version(semester_id, today_str)
        if active_version:
            weekday = date.today().weekday()
            entries = get_timetable_entries(active_version['id'])
            today_entries = [e for e in entries if e['day_of_week'] == weekday]
            marked = get_attendance_for_date(semester_id, today_str)
            
            for entry in today_entries:
                key = f"{entry['subject_id']}_{entry['start_time']}"
                try:
                    class_time = datetime.strptime(f"{today_str} {entry['start_time']}", '%Y-%m-%d %H:%M')
                    if class_time > now and key not in marked:
                        notifications.append({
                            'type': 'reminder',
                            'icon': 'fa-clock',
                            'color': 'info',
                            'message': f"You have {entry['subject_name']} at {entry['start_time']}."
                        })
                except ValueError:
                    pass
    
    # Missed class warnings per subject
    stats = calculate_attendance_stats(semester_id)
    goals = calculate_goals_and_leaves(semester_id, semester['target'])
    
    for sub in stats['subjects']:
        if sub['missed'] >= 3:
            notifications.append({
                'type': 'warning',
                'icon': 'fa-triangle-exclamation',
                'color': 'warning',
                'message': f"You have missed {sub['missed']} {sub['name']} classes."
            })
    
    for sub_g in goals['subject_goals']:
        if sub_g['required'] > 0 and sub_g['required'] <= 5:
            notifications.append({
                'type': 'goal',
                'icon': 'fa-bullseye',
                'color': 'primary',
                'message': f"Attend the next {sub_g['required']} {sub_g['name']} classes to reach {semester['target']}%."
            })
    
    target_int = int(semester['target'])
    if stats['overall']['percentage'] < semester['target'] and goals['required'].get(target_int, 0) > 0:
        req = goals['required'][target_int]
        if req <= 10:
            notifications.append({
                'type': 'goal',
                'icon': 'fa-chart-line',
                'color': 'danger',
                'message': f"Attend the next {req} classes to reach your {semester['target']}% target."
            })
    
    return notifications[:8]

# --- Cancelled Classes & Extra Class Days ---
def add_cancelled_class(semester_id, subject_id, date_str, reason=''):
    conn = get_db()
    conn.execute('INSERT INTO cancelled_classes (semester_id, subject_id, date, reason) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, subject_id, date) DO NOTHING;', (semester_id, subject_id, date_str, reason))
    conn.commit()
    conn.close()

def get_cancelled_classes(semester_id):
    conn = get_db()
    records = conn.execute('''
        SELECT c.*, s.name as subject_name, s.code as subject_code
        FROM cancelled_classes c
        JOIN subjects s ON c.subject_id = s.id
        WHERE c.semester_id = ? ORDER BY c.date DESC;
    ''', (semester_id,)).fetchall()
    conn.close()
    return [dict(r) for r in records]

def delete_cancelled_class(record_id):
    conn = get_db()
    conn.execute('DELETE FROM cancelled_classes WHERE id = ?;', (record_id,))
    conn.commit()
    conn.close()

def add_extra_class_day(semester_id, date_str, day_to_follow, reason=''):
    conn = get_db()
    conn.execute('INSERT INTO extra_class_days (semester_id, date, day_to_follow, reason) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, semester_id, date) DO UPDATE SET day_to_follow=excluded.day_to_follow, reason=excluded.reason;', (semester_id, date_str, day_to_follow, reason))
    conn.commit()
    conn.close()

def get_extra_class_days(semester_id):
    conn = get_db()
    records = conn.execute('SELECT * FROM extra_class_days WHERE semester_id = ? ORDER BY date DESC;', (semester_id,)).fetchall()
    conn.close()
    return [dict(r) for r in records]

def delete_extra_class_day(record_id):
    conn = get_db()
    conn.execute('DELETE FROM extra_class_days WHERE id = ?;', (record_id,))
    conn.commit()
    conn.close()
