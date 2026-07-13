from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session, abort
import database as db
import timetable_import as ti
import auth_db
import os
import re
import shutil
import csv
from datetime import datetime, timedelta, date
import calendar
import openpyxl
from io import BytesIO, StringIO
import secrets
from collections import defaultdict
import smtplib
from email.message import EmailMessage

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'attendance_management_secret_key')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('FLASK_ENV') == 'production'
)

AUTH_PATHS = {'/login', '/logout', '/register', '/forgot_password', '/reset_password', '/test_version'}
AUTH_POST_PATHS = {'/login', '/register', '/forgot_password', '/reset_password', '/admin/invite', '/admin/users/toggle', '/admin/users/delete', '/admin/invitations/cancel', '/admin/invitations/resend', '/admin/invitations/delete'}
LOGIN_FAILURES = defaultdict(list)


def ensure_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']


def send_email(recipient, subject, body):
    smtp_host = os.environ.get('SMTP_HOST')
    if not smtp_host:
        return False
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    smtp_from = os.environ.get('SMTP_FROM', smtp_user or 'noreply@example.com')

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = smtp_from
    message['To'] = recipient
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(message)
    return True


def is_login_rate_limited(identifier, remote_addr):
    key = f"{remote_addr}:{identifier.lower()}"
    now = datetime.now()
    failures = LOGIN_FAILURES[key]
    failures[:] = [ts for ts in failures if now - ts < timedelta(minutes=15)]
    return len(failures) >= 5


def record_login_failure(identifier, remote_addr):
    key = f"{remote_addr}:{identifier.lower()}"
    LOGIN_FAILURES[key].append(datetime.now())


def ensure_admin_account():
    admin_username = (os.environ.get('ADMIN_USERNAME') or 'admin').strip() or 'admin'
    admin_password = (os.environ.get('ADMIN_PASSWORD') or '').strip()

    existing_admin = next((user for user in auth_db.get_users() if user.get('role') == 'admin'), None)
    if existing_admin:
        if admin_password:
            auth_db.update_password(existing_admin['id'], admin_password)
        return existing_admin['id']

    if not admin_password:
        admin_password = secrets.token_urlsafe(16)
        print(f"WARNING: ADMIN_PASSWORD is not set. Generated temporary admin password: {admin_password}")

    admin_id = auth_db.create_user(
        email='admin@example.com',
        username=admin_username,
        password=admin_password,
        role='admin',
        full_name='Administrator',
        is_active=True
    )
    db.ensure_user_db(admin_id)
    return admin_id


@app.before_request
def require_authentication():
    db.set_active_user(session.get('user_id'))
    if request.path.startswith('/static/') or request.path.startswith('/favicon'):
        return None
    if request.path in AUTH_PATHS or request.path.startswith('/reset_password') or request.path.startswith('/register'):
        return None
    if not session.get('user_id'):
        flash('Please sign in to continue.', 'error')
        return redirect(url_for('login'))
    if not auth_db.is_account_active(session['user_id']):
        flash('Your account is disabled. Contact the administrator.', 'error')
        return redirect(url_for('logout'))
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.path in AUTH_POST_PATHS:
        csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
        if csrf_token != session.get('csrf_token'):
            abort(400)
    return None

# Ensure local backups folder exists
BACKUPS_DIR = os.path.join(os.path.dirname(__file__), 'backups')
if not os.path.exists(BACKUPS_DIR):
    os.makedirs(BACKUPS_DIR)

# Initialize database tables
auth_db.init_db()
db.init_db()

if not auth_db.get_users():
    ensure_admin_account()
else:
    ensure_admin_account()

try:
    if db.DB_PATH and db.get_setting('auto_backup', 'true') == 'true':
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"auto_backup_{timestamp}.db"
        dest_path = os.path.join(BACKUPS_DIR, backup_filename)
        shutil.copy(db.DB_PATH, dest_path)
        print(f"Startup auto-backup created successfully: {backup_filename}")
except Exception as e:
    print(f"Startup backup failed: {e}")

# --- Context Processors ---
@app.context_processor
def inject_global_data():
    ensure_csrf_token()
    current_user = None
    is_admin = False
    if session.get('user_id'):
        current_user = auth_db.get_user_by_id(session['user_id'])
        is_admin = bool(current_user and current_user.get('role') == 'admin')

    semesters = db.get_semesters()
    active_sem_id = db.get_setting('active_semester_id')
    
    active_semester = None
    if active_sem_id:
        active_semester = db.get_semester(int(active_sem_id))
    if not active_semester and semesters:
        active_semester = semesters[0]
        db.set_setting('active_semester_id', active_semester['id'])
        
    theme = db.get_setting('theme', 'dark')
    today_str = date.today().strftime('%Y-%m-%d')
    
    notifications = []
    semester_end_max = ''
    semester_progress_percent = 0
    semester_end_date_str = 'Ongoing'
    if active_semester:
        notifications = db.get_notifications(active_semester['id'])
        start_date = datetime.strptime(active_semester['start_date'], '%Y-%m-%d').date()
        _, end_bound = db.get_semester_date_bounds(active_semester)
        semester_end_max = end_bound.strftime('%Y-%m-%d')
        semester_end_date_str = end_bound.strftime('%d %b %Y')
        
        today = date.today()
        duration = (end_bound - start_date).days
        elapsed = (today - start_date).days
        if duration > 0:
            semester_progress_percent = int(min(max((elapsed / duration) * 100, 0), 100))
    
    return {
        'semesters': semesters,
        'active_semester': active_semester,
        'current_theme': theme,
        'today_str': today_str,
        'notifications': notifications,
        'semester_end_max': semester_end_max,
        'custom_goals': db.get_custom_goals(),
        'semester_progress_percent': semester_progress_percent,
        'semester_end_date_str': semester_end_date_str,
        'current_user': current_user,
        'is_admin': is_admin,
        'csrf_token': session.get('csrf_token')
    }

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remote_addr = request.remote_addr or 'unknown'
        if is_login_rate_limited(username, remote_addr):
            flash('Too many failed login attempts. Please try again later.', 'error')
            return render_template('login.html', csrf_token=ensure_csrf_token())
        user = auth_db.get_user_by_username_or_email(username)
        if user and auth_db.verify_password(password, user['password_hash']) and auth_db.is_account_active(user['id']):
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session.permanent = bool(request.form.get('remember_me'))
            db.ensure_user_db(user['id'])
            auth_db.update_last_login(user['id'])
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        record_login_failure(username, remote_addr)
        flash('Invalid login credentials or disabled account.', 'error')
    return render_template('login.html', csrf_token=ensure_csrf_token())


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/register')
def register():
    token = request.args.get('token', '').strip()
    invitation = auth_db.get_valid_invitation(token) if token else None
    if not invitation:
        flash('Invalid or expired invitation.', 'error')
        return redirect(url_for('login'))
    return render_template('register.html', invitation=invitation, token=token, csrf_token=ensure_csrf_token())


@app.route('/register', methods=['POST'])
def register_post():
    token = request.form.get('token', '').strip()
    invitation = auth_db.get_valid_invitation(token) if token else None
    if not invitation:
        flash('Invalid or expired invitation.', 'error')
        return redirect(url_for('login'))

    email = request.form.get('email', '').strip().lower()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    if email != invitation['email']:
        flash('The invitation email does not match this registration.', 'error')
        return redirect(url_for('register', token=token))
    if not username or len(username) < 3:
        flash('Username must be at least 3 characters.', 'error')
        return redirect(url_for('register', token=token))
    if password != confirm_password:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('register', token=token))
    valid, message = auth_db.validate_password(password)
    if not valid:
        flash(message, 'error')
        return redirect(url_for('register', token=token))
    if auth_db.get_user_by_username_or_email(username) or auth_db.get_user_by_email(email):
        flash('That username or email is already in use.', 'error')
        return redirect(url_for('register', token=token))

    user_id = auth_db.create_user(email=email, username=username, password=password)
    db.ensure_user_db(user_id)
    auth_db.mark_invitation_used(invitation['id'])
    flash('Account created successfully. Please sign in.', 'success')
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = auth_db.get_user_by_email(email)
        if user:
            reset_id, token = auth_db.create_password_reset(user['id'])
            reset_link = request.host_url.rstrip('/') + url_for('reset_password', token=token)
            body = f"Use the following link to reset your password:\n\n{reset_link}\n"
            if send_email(email, 'AttendX password reset', body):
                flash('Password reset instructions have been sent.', 'info')
            else:
                flash(f'Password reset link: {reset_link}', 'info')
            return redirect(url_for('login'))
        flash('If an account exists for that email, a reset link has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html', csrf_token=ensure_csrf_token())


@app.route('/reset_password')
def reset_password():
    token = request.args.get('token', '').strip()
    reset = auth_db.get_valid_password_reset(token) if token else None
    if not reset:
        flash('Invalid or expired password reset link.', 'error')
        return redirect(url_for('login'))
    return render_template('reset_password.html', reset=reset, token=token, csrf_token=ensure_csrf_token())


@app.route('/reset_password', methods=['POST'])
def reset_password_post():
    token = request.form.get('token', '').strip()
    reset = auth_db.get_valid_password_reset(token) if token else None
    if not reset:
        flash('Invalid or expired password reset link.', 'error')
        return redirect(url_for('login'))
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    if password != confirm_password:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('reset_password', token=token))
    valid, message = auth_db.validate_password(password)
    if not valid:
        flash(message, 'error')
        return redirect(url_for('reset_password', token=token))
    auth_db.update_password(reset['user_id'], password)
    auth_db.mark_password_reset_used(reset['id'])
    flash('Password updated successfully.', 'success')
    return redirect(url_for('login'))


@app.route('/admin')
def admin_dashboard():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        flash('Administrator access required.', 'error')
        return redirect(url_for('dashboard'))
    auth_db.expire_old_invitations()
    invitations = auth_db.get_invitations()
    for invitation in invitations:
        token = invitation.get('token')
        invitation['invite_link'] = (request.host_url.rstrip('/') + url_for('register', token=token)) if token else None
    return render_template('admin.html', users=auth_db.get_users(), invitations=invitations, csrf_token=ensure_csrf_token())


@app.route('/admin/invite', methods=['POST'])
def admin_invite_user():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Email is required.', 'error')
        return redirect(url_for('admin_dashboard'))
    if auth_db.get_user_by_email(email):
        flash('A user already exists for that email.', 'error')
        return redirect(url_for('admin_dashboard'))
    invitation_id, token = auth_db.create_invitation(email, created_by=session['user_id'])
    invite_link = request.host_url.rstrip('/') + url_for('register', token=token)
    body = f"You have been invited to AttendX. Use this link to create your account:\n\n{invite_link}\n"
    if send_email(email, 'AttendX invitation', body):
        flash(f'Invitation sent to {email}.', 'success')
    else:
        flash(f'Invitation created for {email}. Link: {invite_link}', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users/toggle', methods=['POST'])
def admin_toggle_user():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    user_id = int(request.form.get('user_id'))
    user = auth_db.get_user_by_id(user_id)
    if user:
        auth_db.set_user_status(user_id, not bool(user['is_active']))
        flash('User status updated.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users/delete', methods=['POST'])
def admin_delete_user():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    user_id = int(request.form.get('user_id'))
    auth_db.delete_user(user_id)
    flash('User deleted.', 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/invitations/cancel', methods=['POST'])
def admin_cancel_invitation():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    invitation_id = int(request.form.get('invitation_id'))
    auth_db.cancel_invitation(invitation_id)
    flash('Invitation cancelled.', 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/invitations/delete', methods=['POST'])
def admin_delete_invitation():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    invitation_id = int(request.form.get('invitation_id'))
    auth_db.delete_invitation(invitation_id)
    flash('Invitation record deleted.', 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/invitations/resend', methods=['POST'])
def admin_resend_invitation():
    if not session.get('user_id') or auth_db.get_user_by_id(session['user_id']).get('role') != 'admin':
        abort(403)
    invitation_id = int(request.form.get('invitation_id'))
    invitation = auth_db.get_invitation_by_id(invitation_id)
    if invitation and invitation['status'] != 'accepted':
        if invitation['status'] == 'pending':
            auth_db.cancel_invitation(invitation_id)
        new_id, token = auth_db.create_invitation(invitation['email'], created_by=session['user_id'])
        invite_link = request.host_url.rstrip('/') + url_for('register', token=token)
        flash(f'Resent invitation to {invitation["email"]}. Link: {invite_link}', 'success')
    return redirect(url_for('admin_dashboard'))


# Dashboard
@app.route('/')
def dashboard():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('dashboard.html', active_semester=None)
        
    sem_id = int(active_sem_id)
    semester = db.get_semester(sem_id)
    if not semester:
        return render_template('dashboard.html', active_semester=None)
        
    # Get attendance stats (auto-sync from timetable first)
    db.sync_attendance_from_timetable(sem_id)
    stats = db.calculate_attendance_stats(sem_id)
    
    # Calculate goals and safe leaves
    goals_leaves = db.calculate_goals_and_leaves(sem_id, semester['target'])
    
    # Today's scheduled classes
    today_str = date.today().strftime('%Y-%m-%d')
    weekday = date.today().weekday() # 0 = Monday
    
    special_day = db.get_special_day_status(sem_id, today_str)
    
    today_timetable = []
    if not special_day:
        active_version = db.resolve_timetable_version(sem_id, today_str)
        if active_version:
            entries = db.get_timetable_entries(active_version['id'])
            # Filter entries for today's weekday
            today_entries = [e for e in entries if e['day_of_week'] == weekday]
            
            # Check marked status
            marked_today = db.get_attendance_for_date(sem_id, today_str)
            for entry in today_entries:
                key = f"{entry['subject_id']}_{entry['start_time']}"
                marked = key in marked_today
                today_timetable.append({
                    'subject_name': entry['subject_name'],
                    'start_time': entry['start_time'],
                    'end_time': entry['end_time'],
                    'room': entry['room'],
                    'subject_id': entry['subject_id'],
                    'marked': marked,
                    'marked_status': marked_today[key]['status'] if marked else None
                })
                
    return render_template(
        'dashboard.html',
        stats=stats,
        goals_leaves=goals_leaves,
        today_timetable=today_timetable,
        special_day=special_day,
        upcoming_classes=db.get_upcoming_classes(sem_id, days=7),
        leave_summary=db.get_leave_summary(sem_id)
    )

# Set Active Semester
@app.route('/set_active_semester', methods=['POST'])
def set_active_semester():
    sem_id = request.form.get('semester_id')
    if sem_id:
        db.set_setting('active_semester_id', sem_id)
        flash("Active semester updated.", "success")
    return redirect(request.referrer or '/')

# Theme setting endpoint (via Ajax)
@app.route('/save_theme_setting', methods=['POST'])
def save_theme_setting():
    data = request.get_json()
    if data and 'theme' in data:
        db.set_setting('theme', data['theme'])
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

# Quick Start: Create semester + upload timetable in one step
@app.route('/quick_start', methods=['POST'])
def quick_start():
    name = request.form.get('semester_name', '').strip()
    start_date = request.form.get('start_date', '').strip()
    file = request.files.get('timetable_file')
    
    if not name:
        flash("Please provide a semester name.", "error")
        return redirect('/')
    
    if not start_date:
        flash("Start date is required.", "error")
        return redirect('/')
    
    if not file or file.filename == '':
        flash("Please upload a timetable file.", "error")
        return redirect('/')
    
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in ('.csv', '.xlsx'):
        flash("Invalid file format. Please upload an Excel (.xlsx) or CSV (.csv) file.", "error")
        return redirect('/')
    
    # Create semester with start date and default 75% target
    sem_id = db.add_semester(name, start_date=start_date)
    db.set_setting('active_semester_id', sem_id)
    
    # Parse timetable file
    try:
        rows = ti.parse_timetable_file(file, filename)
    except Exception as e:
        flash(f"Error reading file: {e}. Semester created but timetable could not be imported.", "warning")
        return redirect('/')
    
    if not rows:
        flash(f"Semester '{name}' created, but no data rows found. Check that row 1 has column headers (Day, Subject, Start Time, End Time).", "warning")
        return redirect('/')
    
    ver_id = db.add_timetable_version(sem_id, "Initial Timetable", start_date, None)
    result = ti.import_timetable_rows(db, sem_id, ver_id, rows)
    
    if result['success'] == 0:
        db.delete_timetable_version(ver_id)
        sk = result['skipped']
        flash(
            f"Semester created but timetable import failed: 0 classes loaded from {result['total_rows']} rows. "
            f"Skipped — incomplete: {sk['incomplete']}, bad day: {sk['invalid_day']}, bad time: {sk['invalid_time']}. "
            f"Required columns: Day, Subject, Start Time, End Time.",
            "error"
        )
        return redirect('/')
    
    sync = db.sync_attendance_from_timetable(sem_id)
    subjects_created = len(db.get_subjects(sem_id))
    flash(
        f"You're all set! Semester '{name}' created with {subjects_created} subjects, "
        f"{result['success']} class slots, and {sync['created']} attendance records auto-calculated.",
        "success"
    )
    return redirect('/')

# Semesters & Subjects CRUD
@app.route('/semesters')
def semesters_page():
    semesters = db.get_semesters()
    active_sem_id = db.get_setting('active_semester_id')
    subjects = []
    active_semester = None
    subject_stats = {}
    
    if active_sem_id:
        active_semester = db.get_semester(int(active_sem_id))
        if active_semester:
            subjects = db.get_subjects(active_semester['id'])
            subject_stats = {s['id']: s for s in db.calculate_attendance_stats(active_semester['id'])['subjects']}
            
    return render_template('semesters.html', semesters=semesters, active_semester=active_semester, subjects=subjects, subject_stats=subject_stats)

@app.route('/add_semester', methods=['POST'])
def add_semester():
    name = request.form.get('name')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date') or None
    target = float(request.form.get('target', 75.0))
    notes = request.form.get('notes', '')
    working_days = ','.join(request.form.getlist('working_days')) or '0,1,2,3,4'
    
    if not name or not start_date:
        flash("Semester name and start date are required.", "error")
        return redirect(url_for('semesters_page'))
    
    sem_id = db.add_semester(name, start_date, end_date, target, notes, working_days)
    db.set_setting('active_semester_id', sem_id)
    flash("Semester created successfully and set as active.", "success")
    return redirect(url_for('semesters_page'))

@app.route('/edit_semester', methods=['POST'])
def edit_semester():
    sem_id = int(request.form.get('semester_id'))
    name = request.form.get('name')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date') or None
    target = float(request.form.get('target', 75.0))
    notes = request.form.get('notes', '')
    working_days = ','.join(request.form.getlist('working_days')) or '0,1,2,3,4'
    
    if not name or not start_date:
        flash("Semester name and start date are required.", "error")
        return redirect(url_for('semesters_page'))
    
    db.update_semester(sem_id, name, start_date, end_date, target, notes, working_days)
    flash("Semester updated successfully.", "success")
    return redirect(url_for('semesters_page'))

@app.route('/delete_semester/<int:semester_id>')
def delete_semester(semester_id):
    db.delete_semester(semester_id)
    active_sem_id = db.get_setting('active_semester_id')
    if active_sem_id and int(active_sem_id) == semester_id:
        db.set_setting('active_semester_id', '')
    flash("Semester and all related data deleted.", "warning")
    return redirect(url_for('semesters_page'))

@app.route('/add_subject', methods=['POST'])
def add_subject():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        flash("No active semester to add subject to.", "error")
        return redirect(url_for('semesters_page'))
        
    name = request.form.get('name')
    code = request.form.get('code', '')
    faculty = request.form.get('faculty', '')
    credits = int(request.form.get('credits', 4))
    
    db.add_subject(int(active_sem_id), name, code, faculty, credits)
    flash("Subject added.", "success")
    return redirect(url_for('semesters_page'))

@app.route('/edit_subject', methods=['POST'])
def edit_subject():
    subject_id = int(request.form.get('subject_id'))
    name = request.form.get('name')
    code = request.form.get('code', '')
    faculty = request.form.get('faculty', '')
    credits = int(request.form.get('credits', 4))
    
    db.update_subject(subject_id, name, code, faculty, credits)
    flash("Subject updated.", "success")
    return redirect(url_for('semesters_page'))

@app.route('/delete_subject/<int:subject_id>')
def delete_subject(subject_id):
    db.delete_subject(subject_id)
    flash("Subject deleted.", "warning")
    return redirect(url_for('semesters_page'))


# Timetable CRUD & Upload
@app.route('/timetable')
def timetable_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('timetable.html', versions=[], entries=[])
        
    sem_id = int(active_sem_id)
    versions = db.get_timetable_versions(sem_id)
    subjects = db.get_subjects(sem_id)
    
    selected_version_id = request.args.get('version_id')
    selected_version = None
    entries = []
    
    if selected_version_id:
        conn = db.get_db()
        selected_version = conn.execute("SELECT * FROM timetable_versions WHERE id = ?;", (selected_version_id,)).fetchone()
        conn.close()
    elif versions:
        selected_version = versions[0]
        
    if selected_version:
        entries = db.get_timetable_entries(selected_version['id'])
        
    return render_template(
        'timetable.html',
        versions=versions,
        subjects=subjects,
        selected_version=selected_version,
        entries=entries
    )

@app.route('/add_version', methods=['POST'])
def add_version():
    active_sem_id = db.get_setting('active_semester_id')
    name = request.form.get('version_name')
    effective_date = request.form.get('effective_date')
    end_date = request.form.get('end_date') or None
    
    new_id = db.add_timetable_version(int(active_sem_id), name, effective_date, end_date)
    flash("Timetable version created.", "success")
    return redirect(url_for('timetable_page', version_id=new_id))

@app.route('/delete_version/<int:version_id>')
def delete_version(version_id):
    db.delete_timetable_version(version_id)
    flash("Timetable version deleted.", "warning")
    return redirect(url_for('timetable_page'))

@app.route('/duplicate_version', methods=['POST'])
def duplicate_version():
    active_sem_id = db.get_setting('active_semester_id')
    source_id = int(request.form.get('source_version_id'))
    name = request.form.get('version_name')
    effective_date = request.form.get('effective_date')
    end_date = request.form.get('end_date') or None
    
    new_id = db.add_timetable_version(int(active_sem_id), name, effective_date, end_date)
    
    # Copy entries
    conn = db.get_db()
    entries = conn.execute("SELECT * FROM timetable_entries WHERE version_id = ?;", (source_id,)).fetchall()
    for e in entries:
        db.add_timetable_entry(
            new_id,
            e['subject_id'],
            e['day_of_week'],
            e['start_time'],
            e['end_time'],
            e['room'],
            e['notes']
        )
    conn.close()
    
    flash("Timetable version duplicated successfully.", "success")
    return redirect(url_for('timetable_page', version_id=new_id))

@app.route('/add_timetable_entry', methods=['POST'])
def add_timetable_entry():
    version_id = int(request.form.get('version_id'))
    subject_id = int(request.form.get('subject_id'))
    day_of_week = int(request.form.get('day_of_week'))
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    room = request.form.get('room', '')
    notes = request.form.get('notes', '')
    
    db.add_timetable_entry(version_id, subject_id, day_of_week, start_time, end_time, room, notes)
    flash("Class slot added.", "success")
    return redirect(url_for('timetable_page', version_id=version_id))

@app.route('/edit_timetable_entry', methods=['POST'])
def edit_timetable_entry():
    entry_id = int(request.form.get('entry_id'))
    version_id = int(request.form.get('version_id'))
    subject_id = int(request.form.get('subject_id'))
    day_of_week = int(request.form.get('day_of_week'))
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    room = request.form.get('room', '')
    notes = request.form.get('notes', '')
    
    db.update_timetable_entry(entry_id, subject_id, day_of_week, start_time, end_time, room, notes)
    flash("Class slot updated.", "success")
    return redirect(url_for('timetable_page', version_id=version_id))

@app.route('/delete_timetable_entry/<int:entry_id>')
def delete_timetable_entry(entry_id):
    version_id = request.args.get('version_id')
    conn = db.get_db()
    conn.execute("DELETE FROM timetable_entries WHERE id = ?;", (entry_id,))
    conn.commit()
    conn.close()
    flash("Class slot removed.", "warning")
    return redirect(url_for('timetable_page', version_id=version_id))


# Timetable Upload Helper
@app.route('/upload_timetable', methods=['POST'])
def upload_timetable():
    active_sem_id = int(db.get_setting('active_semester_id'))
    version_name = request.form.get('version_name')
    effective_date = request.form.get('effective_date')
    end_date = request.form.get('end_date') or None
    file = request.files.get('file')
    
    if not file or file.filename == '':
        flash("No file selected.", "error")
        return redirect(url_for('timetable_page'))
    
    filename = file.filename
    
    try:
        rows = ti.parse_timetable_file(file, filename)
        if not rows:
            flash(
                "No timetable data found. Your file may have a title row before headers, "
                "use different column names, or be in grid format (days as columns). "
                "Supported: list format (Day, Subject, Start/End Time) OR grid format (Time | Mon | Tue | ...). "
                "Save as .xlsx if using Excel.",
                "error"
            )
            return redirect(url_for('timetable_page'))
        
        ver_id = db.add_timetable_version(active_sem_id, version_name, effective_date, end_date)
        result = ti.import_timetable_rows(db, active_sem_id, ver_id, rows)
        
        if result['success'] == 0:
            db.delete_timetable_version(ver_id)
            sk = result['skipped']
            flash(
                f"Import failed: 0 classes from {result['total_rows']} rows. "
                f"Incomplete rows: {sk['incomplete']}, invalid day: {sk['invalid_day']}, invalid time: {sk['invalid_time']}. "
                f"Check column names and time format (e.g. 09:00 or 9:00 AM).",
                "error"
            )
            return redirect(url_for('timetable_page'))
        
        sync = db.sync_attendance_from_timetable(active_sem_id)
        flash(
            f"Timetable imported: {result['success']} classes loaded. "
            f"{sync['created']} attendance records auto-calculated.",
            "success"
        )
        return redirect(url_for('timetable_page', version_id=ver_id))
        
    except Exception as e:
        flash(f"Error parsing file: {e}", "error")
        return redirect(url_for('timetable_page'))


@app.route('/sync_attendance', methods=['POST'])
def sync_attendance():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        flash("No active semester.", "error")
        return redirect(request.referrer or '/')
    result = db.sync_attendance_from_timetable(int(active_sem_id))
    flash(f"Attendance recalculated: {result['created']} new records from timetable.", "success")
    return redirect(request.referrer or '/')


@app.route('/daily')
def daily_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('daily.html', active_semester=None)
        
    sem_id = int(active_sem_id)
    
    selected_date_str = request.args.get('date')
    if not selected_date_str:
        selected_date_str = date.today().strftime('%Y-%m-%d')
        
    selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    weekday = selected_date.weekday()
    
    yesterday_str = (selected_date - timedelta(days=1)).strftime('%Y-%m-%d')
    tomorrow_str = (selected_date + timedelta(days=1)).strftime('%Y-%m-%d')
    
    special_day = db.get_special_day_status(sem_id, selected_date_str)
    
    timetable_entries = []
    version_name = ""
    timetable_version_id = None
    
    if not special_day:
        active_version = db.resolve_timetable_version(sem_id, selected_date_str)
        if active_version:
            timetable_version_id = active_version['id']
            version_name = active_version['version_name']
            entries = db.get_timetable_entries(active_version['id'])
            timetable_entries = [e for e in entries if e['day_of_week'] == weekday]
            
    attendance_records = db.get_attendance_for_date(sem_id, selected_date_str)
    subjects = db.get_subjects(sem_id)
    
    return render_template(
        'daily.html',
        selected_date_str=selected_date_str,
        yesterday_str=yesterday_str,
        tomorrow_str=tomorrow_str,
        special_day=special_day,
        timetable_entries=timetable_entries,
        version_name=version_name,
        timetable_version_id=timetable_version_id,
        attendance_records=attendance_records,
        subjects=subjects
    )

@app.route('/save_daily_attendance', methods=['POST'])
def save_daily_attendance():
    active_sem_id = int(db.get_setting('active_semester_id'))
    date_str = request.form.get('date')
    version_id = request.form.get('version_id')
    v_id = int(version_id) if version_id else None
    
    # Find all keys in post body
    for key, value in request.form.items():
        if key.startswith('status_'):
            # format status_subjectId_startTime
            parts = key.split('_')
            subject_id = int(parts[1])
            time_str = parts[2]
            
            # Fetch note if exists
            note_key = f"notes_{subject_id}_{time_str}"
            notes = request.form.get(note_key, "")
            
            status = 'attended' if value == 'attended' else 'missed'
            db.mark_attendance(active_sem_id, subject_id, date_str, time_str, status, v_id, notes)
            
    # Also look for checkboxes that were unchecked (missed).
    # Since unchecked checkboxes aren't submitted in standard POST, we find all keys in DB for this version/day and mark missed if not in form.
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    weekday = selected_date.weekday()
    if v_id:
        entries = db.get_timetable_entries(v_id)
        day_entries = [e for e in entries if e['day_of_week'] == weekday]
        for entry in day_entries:
            key = f"status_{entry['subject_id']}_{entry['start_time']}"
            if key not in request.form:
                note_key = f"notes_{entry['subject_id']}_{entry['start_time']}"
                notes = request.form.get(note_key, "")
                db.mark_attendance(active_sem_id, entry['subject_id'], date_str, entry['start_time'], 'missed', v_id, notes)

    flash("Attendance saved successfully.", "success")
    return redirect(url_for('daily_page', date=date_str))


# Holidays & Offs
@app.route('/holidays')
def holidays_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('holidays.html', holidays=[], no_class_days=[], leave_summary=None)
        
    sem_id = int(active_sem_id)
    subjects = db.get_subjects(sem_id)
    holidays = db.get_holidays(sem_id)
    no_class_days = db.get_no_class_days(sem_id)
    leave_summary = db.get_leave_summary(sem_id)
    leave_by_date = {d['date']: d['classes_excluded'] for d in leave_summary['details']}
    
    cancelled_classes = db.get_cancelled_classes(sem_id)
    extra_class_days = db.get_extra_class_days(sem_id)
    
    return render_template(
        'holidays.html',
        subjects=subjects,
        holidays=holidays,
        no_class_days=no_class_days,
        leave_summary=leave_summary,
        leave_by_date=leave_by_date,
        cancelled_classes=cancelled_classes,
        extra_class_days=extra_class_days
    )

@app.route('/upload_leaves', methods=['POST'])
def upload_leaves():
    active_sem_id = int(db.get_setting('active_semester_id'))
    file = request.files.get('file')
    if not file or file.filename == '':
        flash("No file selected.", "error")
        return redirect(url_for('holidays_page'))
    try:
        rows = ti.parse_leaves_file(file, file.filename)
        if not rows:
            flash("No leave dates found. File needs columns: Date, Reason (or just a list of dates).", "error")
            return redirect(url_for('holidays_page'))
        count = db.import_leaves_from_rows(active_sem_id, rows)
        flash(f"Imported {count} leave day(s). Attendance recalculated — excluded from stats.", "success")
    except Exception as e:
        flash(f"Error importing leaves: {e}", "error")
    return redirect(url_for('holidays_page'))

@app.route('/add_holiday', methods=['POST'])
def add_holiday():
    active_sem_id = int(db.get_setting('active_semester_id'))
    date_str = request.form.get('date')
    reason = request.form.get('reason')
    
    db.add_holiday(active_sem_id, date_str, reason)
    db.sync_attendance_from_timetable(active_sem_id)
    flash("Holiday added. Attendance for this date excluded from calculations.", "success")
    return redirect(url_for('holidays_page'))

@app.route('/delete_holiday/<int:holiday_id>')
def delete_holiday(holiday_id):
    active_sem_id = db.get_setting('active_semester_id')
    db.delete_holiday(holiday_id)
    if active_sem_id:
        db.sync_attendance_from_timetable(int(active_sem_id))
    flash("Holiday removed. Attendance recalculated.", "warning")
    return redirect(url_for('holidays_page'))

@app.route('/add_no_class_day', methods=['POST'])
def add_no_class_day():
    active_sem_id = int(db.get_setting('active_semester_id'))
    date_str = request.form.get('date')
    reason = request.form.get('reason')
    description = request.form.get('description', '')
    
    db.add_no_class_day(active_sem_id, date_str, reason, description)
    db.sync_attendance_from_timetable(active_sem_id)
    flash("No-class day recorded. Attendance excluded for this date.", "success")
    return redirect(url_for('holidays_page'))

@app.route('/delete_no_class_day/<int:no_class_day_id>')
def delete_no_class_day(no_class_day_id):
    active_sem_id = db.get_setting('active_semester_id')
    db.delete_no_class_day(no_class_day_id)
    if active_sem_id:
        db.sync_attendance_from_timetable(int(active_sem_id))
    flash("Cancellation removed. Attendance recalculated.", "warning")
    return redirect(url_for('holidays_page'))

@app.route('/add_cancelled_class', methods=['POST'])
def add_cancelled_class():
    active_sem_id = int(db.get_setting('active_semester_id'))
    subject_id = request.form.get('subject_id')
    date_str = request.form.get('date')
    reason = request.form.get('reason', '')
    
    db.add_cancelled_class(active_sem_id, subject_id, date_str, reason)
    db.sync_attendance_from_timetable(active_sem_id)
    flash("Subject class cancelled for the date.", "success")
    return redirect(url_for('holidays_page'))

@app.route('/delete_cancelled_class/<int:cancelled_id>')
def delete_cancelled_class(cancelled_id):
    active_sem_id = db.get_setting('active_semester_id')
    db.delete_cancelled_class(cancelled_id)
    if active_sem_id:
        db.sync_attendance_from_timetable(int(active_sem_id))
    flash("Cancelled class removed. Attendance recalculated.", "warning")
    return redirect(url_for('holidays_page'))

@app.route('/add_extra_class_day', methods=['POST'])
def add_extra_class_day():
    active_sem_id = int(db.get_setting('active_semester_id'))
    date_str = request.form.get('date')
    day_to_follow = request.form.get('day_to_follow')
    reason = request.form.get('reason', '')
    
    db.add_extra_class_day(active_sem_id, date_str, day_to_follow, reason)
    db.sync_attendance_from_timetable(active_sem_id)
    flash("Extra class routine added.", "success")
    return redirect(url_for('holidays_page'))

@app.route('/delete_extra_class_day/<int:extra_id>')
def delete_extra_class_day(extra_id):
    active_sem_id = db.get_setting('active_semester_id')
    db.delete_extra_class_day(extra_id)
    if active_sem_id:
        db.sync_attendance_from_timetable(int(active_sem_id))
    flash("Extra class routine removed. Attendance recalculated.", "warning")
    return redirect(url_for('holidays_page'))


# Monthly Calendar & Modals API
@app.route('/calendar')
def calendar_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('calendar.html')
        
    sem_id = int(active_sem_id)
    
    year_arg = request.args.get('year')
    month_arg = request.args.get('month')
    
    today = date.today()
    year = int(year_arg) if year_arg else today.year
    month = int(month_arg) if month_arg else today.month
    
    # Generate Calendar days
    cal = calendar.Calendar(firstweekday=0) # starts Monday
    month_cells = cal.monthdayscalendar(year, month)
    
    calendar_cells = []
    for week in month_cells:
        for day in week:
            if day == 0:
                calendar_cells.append({'is_empty': True})
            else:
                curr_date = date(year, month, day)
                date_str = curr_date.strftime('%Y-%m-%d')
                is_today = (curr_date == today)
                calendar_cells.append({
                    'is_empty': False,
                    'day': day,
                    'date_str': date_str,
                    'is_today': is_today
                })
                
    # Load events for statuses
    events = db.get_calendar_events(sem_id, year, month)
    
    # Date navigation helpers
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    month_name = calendar.month_name[month]
    
    return render_template(
        'calendar.html',
        calendar_cells=calendar_cells,
        events=events,
        year=year,
        month=month,
        month_name=month_name,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year
    )

@app.route('/api/date_details')
def api_date_details():
    active_sem_id = int(db.get_setting('active_semester_id'))
    date_str = request.args.get('date')
    
    special_day = db.get_special_day_status(active_sem_id, date_str)
    if special_day:
        return jsonify({'special_day': special_day})
        
    # Get timetable classes scheduled for that date
    dt = datetime.strptime(date_str, '%Y-%m-%d').date()
    weekday = dt.weekday()
    
    active_version = db.resolve_timetable_version(active_sem_id, date_str)
    if not active_version:
        return jsonify({'classes': []})
        
    entries = db.get_timetable_entries(active_version['id'])
    day_entries = [e for e in entries if e['day_of_week'] == weekday]
    
    marked = db.get_attendance_for_date(active_sem_id, date_str)
    
    classes_list = []
    for entry in day_entries:
        key = f"{entry['subject_id']}_{entry['start_time']}"
        rec = marked.get(key)
        classes_list.append({
            'subject_id': entry['subject_id'],
            'subject_name': entry['subject_name'],
            'subject_code': entry['subject_code'],
            'subject_faculty': entry['subject_faculty'],
            'start_time': entry['start_time'],
            'end_time': entry['end_time'],
            'room': entry['room'],
            'version_id': active_version['id'],
            'status': rec['status'] if rec else 'unmarked',
            'notes': rec['notes'] if rec else ''
        })
        
    return jsonify({'classes': classes_list})

@app.route('/api/quick_mark', methods=['POST'])
def api_quick_mark():
    active_sem_id = int(db.get_setting('active_semester_id'))
    data = request.get_json()
    
    date_str = data.get('date')
    subject_id = int(data.get('subject_id'))
    time_str = data.get('time')
    status = data.get('status')
    version_id = data.get('version_id')
    v_id = int(version_id) if version_id else None
    
    db.mark_attendance(active_sem_id, subject_id, date_str, time_str, status, v_id)
    return jsonify({'success': True})


# Predictions & Custom Calculators
@app.route('/prediction')
def prediction_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('prediction.html')
        
    sem_id = int(active_sem_id)
    semester = db.get_semester(sem_id)
    subjects = db.get_subjects(sem_id)
    stats = db.calculate_attendance_stats(sem_id)
    goals_leaves = db.calculate_goals_and_leaves(sem_id, semester['target'])
    
    return render_template(
        'prediction.html',
        subjects=subjects,
        stats=stats,
        goals_leaves=goals_leaves
    )

@app.route('/api/simulate_prediction', methods=['POST'])
def api_simulate_prediction():
    active_sem_id = int(db.get_setting('active_semester_id'))
    data = request.get_json()
    
    pred_type = data.get('prediction_type')
    target_date = data.get('target_date')
    param = data.get('param')
    
    results = db.run_attendance_prediction(active_sem_id, pred_type, target_date, param)
    if not results:
        return jsonify({'error': 'No timetable config found'}), 400
        
    return jsonify(results)

@app.route('/prediction/range')
def prediction_range():
    active_sem_id = int(db.get_setting('active_semester_id'))
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Calculate range specific stats
    conn = db.get_db()
    subjects = db.get_subjects(active_sem_id)
    
    range_stats = []
    total_att = 0
    total_miss = 0
    
    for sub in subjects:
        sub_id = sub['id']
        att_row = conn.execute("""
            SELECT 
                SUM(CASE WHEN status = 'attended' THEN 1 ELSE 0 END) as attended,
                SUM(CASE WHEN status = 'missed' THEN 1 ELSE 0 END) as missed
            FROM attendance
            WHERE subject_id = ? AND date BETWEEN ? AND ?;
        """, (sub_id, start_date, end_date)).fetchone()
        
        att = att_row['attended'] or 0
        miss = att_row['missed'] or 0
        tot = att + miss
        pct = (att / tot * 100) if tot > 0 else 100.0
        
        range_stats.append({
            'name': sub['name'],
            'code': sub['code'],
            'attended': att,
            'missed': miss,
            'total': tot,
            'percentage': round(pct, 2)
        })
        
        total_att += att
        total_miss += miss
        
    conn.close()
    
    overall_cond = total_att + total_miss
    overall_pct = (total_att / overall_cond * 100) if overall_cond > 0 else 100.0
    
    return render_template(
        'prediction_range.html',
        start_date=start_date,
        end_date=end_date,
        subjects=range_stats,
        overall_attended=total_att,
        overall_missed=total_miss,
        overall_conducted=overall_cond,
        overall_percentage=round(overall_pct, 2)
    )


# Reports, History & Exports
@app.route('/reports')
def reports_page():
    active_sem_id = db.get_setting('active_semester_id')
    if not active_sem_id:
        return render_template('reports.html')
        
    sem_id = int(active_sem_id)
    subjects = db.get_subjects(sem_id)
    
    # Filter variables
    subject_id = request.args.get('subject_id', '')
    status = request.args.get('status', '')
    faculty = request.args.get('faculty', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = """
        SELECT a.*, s.name as subject_name, s.code as subject_code, s.faculty as subject_faculty, v.version_name
        FROM attendance a
        JOIN subjects s ON a.subject_id = s.id
        LEFT JOIN timetable_versions v ON a.version_id = v.id
        WHERE a.semester_id = ?
    """
    params = [sem_id]
    
    if subject_id:
        query += " AND a.subject_id = ?"
        params.append(int(subject_id))
    if status:
        query += " AND a.status = ?"
        params.append(status)
    if faculty:
        query += " AND s.faculty LIKE ?"
        params.append(f'%{faculty}%')
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
        
    query += " ORDER BY a.date DESC, a.time DESC;"
    
    conn = db.get_db()
    logs = conn.execute(query, params).fetchall()
    conn.close()
    
    filters = {
        'subject_id': subject_id,
        'status': status,
        'faculty': faculty,
        'start_date': start_date,
        'end_date': end_date
    }
    
    return render_template('reports.html', subjects=subjects, logs=logs, filters=filters)

@app.route('/edit_log', methods=['POST'])
def edit_log():
    log_id = int(request.form.get('log_id'))
    status = request.form.get('status')
    notes = request.form.get('notes', '')
    
    conn = db.get_db()
    conn.execute("UPDATE attendance SET status = ?, notes = ? WHERE id = ?;", (status, notes, log_id))
    conn.commit()
    conn.close()
    flash("Attendance log record updated.", "success")
    return redirect(request.referrer or url_for('reports_page'))

@app.route('/delete_log/<int:log_id>')
def delete_log(log_id):
    db.delete_attendance(log_id)
    flash("Attendance record deleted.", "warning")
    return redirect(request.referrer or url_for('reports_page'))

@app.route('/reports/export')
def export_reports():
    active_sem_id = int(db.get_setting('active_semester_id'))
    fmt = request.args.get('format', 'csv')
    
    subject_id = request.args.get('subject_id', '')
    status = request.args.get('status', '')
    faculty = request.args.get('faculty', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = """
        SELECT a.date, a.time, s.name as subject_name, s.code as subject_code, s.faculty as subject_faculty, a.status, a.notes
        FROM attendance a
        JOIN subjects s ON a.subject_id = s.id
        WHERE a.semester_id = ?
    """
    params = [active_sem_id]
    
    if subject_id:
        query += " AND a.subject_id = ?"
        params.append(int(subject_id))
    if status:
        query += " AND a.status = ?"
        params.append(status)
    if faculty:
        query += " AND s.faculty LIKE ?"
        params.append(f'%{faculty}%')
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
        
    query += " ORDER BY a.date DESC, a.time DESC;"
    
    conn = db.get_db()
    logs = conn.execute(query, params).fetchall()
    conn.close()
    
    if fmt == 'csv':
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Time', 'Subject Name', 'Subject Code', 'Faculty', 'Status', 'Notes'])
        for log in logs:
            writer.writerow([log['date'], log['time'], log['subject_name'], log['subject_code'], log['subject_faculty'] or '', log['status'].capitalize(), log['notes']])
        
        output.seek(0)
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='attendance_report.csv'
        )
        
    elif fmt == 'excel':
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Attendance Report"
        
        headers = ['Date', 'Time', 'Subject Name', 'Subject Code', 'Faculty', 'Status', 'Notes']
        ws.append(headers)
        
        for log in logs:
            ws.append([log['date'], log['time'], log['subject_name'], log['subject_code'], log['subject_faculty'] or '', log['status'].capitalize(), log['notes']])
            
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        
        return send_file(
            out,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='attendance_report.xlsx'
        )
    
    elif fmt == 'pdf':
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        
        out = BytesIO()
        doc = SimpleDocTemplate(out, pagesize=landscape(letter))
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("Attendance Report", styles['Title']),
            Spacer(1, 12)
        ]
        
        table_data = [['Date', 'Time', 'Subject', 'Code', 'Faculty', 'Status', 'Notes']]
        for log in logs:
            table_data.append([
                log['date'], log['time'], log['subject_name'], log['subject_code'] or '',
                log['subject_faculty'] or '', log['status'].capitalize(), log['notes'] or ''
            ])
        
        t = Table(table_data, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ]))
        elements.append(t)
        doc.build(elements)
        out.seek(0)
        
        return send_file(
            out,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='attendance_report.pdf'
        )
        
    return redirect(url_for('reports_page'))


# Settings & Database Backup Management
@app.route('/settings')
def settings_page():
    # Load all settings
    keys = ['default_target', 'first_day_of_week', 'date_format', 'time_format', 'auto_backup', 'custom_goals']
    settings_dict = {}
    for key in keys:
        settings_dict[key] = db.get_setting(key)
        
    # Get local backups history
    conn = db.get_db()
    backup_logs = conn.execute("SELECT * FROM backup_history ORDER BY backup_time DESC;").fetchall()
    conn.close()
    
    return render_template('settings.html', settings=settings_dict, backup_logs=backup_logs)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    db.set_setting('default_target', request.form.get('default_target'))
    db.set_setting('first_day_of_week', request.form.get('first_day_of_week'))
    db.set_setting('date_format', request.form.get('date_format'))
    db.set_setting('time_format', request.form.get('time_format'))
    db.set_setting('custom_goals', request.form.get('custom_goals', '75,80,85,90'))
    
    auto_backup = 'true' if request.form.get('auto_backup') else 'false'
    db.set_setting('auto_backup', auto_backup)
    
    flash("Preferences saved successfully.", "success")
    return redirect(url_for('settings_page'))

# Backup: Export Database file
@app.route('/backup/export')
def backup_export():
    if not db.DB_PATH:
        flash("Exporting SQLite database file is not supported in PostgreSQL mode.", "error")
        return redirect(url_for('settings_page'))
    return send_file(db.DB_PATH, as_attachment=True, download_name='attendance_backup.db')

# Backup: Import/Overwrite database
@app.route('/backup/import', methods=['POST'])
def backup_import():
    if not db.DB_PATH:
        flash("Restoring SQLite database file is not supported in PostgreSQL mode.", "error")
        return redirect(url_for('settings_page'))
    file = request.files.get('db_file')
    if not file or file.filename == '':
        flash("No file selected.", "error")
        return redirect(url_for('settings_page'))
        
    # Overwrite attendance.db
    file.save(db.DB_PATH)
    flash("Database successfully restored from file.", "success")
    return redirect(url_for('settings_page'))

# Backup: Manual local restore point creation
@app.route('/backup/manual_local')
def backup_manual_local():
    if not db.DB_PATH:
        flash("Local restore points are only supported in SQLite mode.", "error")
        return redirect(url_for('settings_page'))
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"manual_backup_{timestamp}.db"
        dest_path = os.path.join(BACKUPS_DIR, backup_filename)
        shutil.copy(db.DB_PATH, dest_path)
        
        # Log to db history
        conn = db.get_db()
        conn.execute("INSERT INTO backup_history (filename, status) VALUES (?, ?);", (backup_filename, 'Success'))
        conn.commit()
        conn.close()
        
        flash("Local restore point created successfully.", "success")
    except Exception as e:
        flash(f"Failed to create restore point: {e}", "error")
        
    return redirect(url_for('settings_page'))

# Backup: Restore database from local file
@app.route('/backup/restore_local/<int:backup_id>')
def backup_restore_local(backup_id):
    if not db.DB_PATH:
        flash("Restoring from local checkpoints is only supported in SQLite mode.", "error")
        return redirect(url_for('settings_page'))
    conn = db.get_db()
    row = conn.execute("SELECT filename FROM backup_history WHERE id = ?;", (backup_id,)).fetchone()
    conn.close()
    
    if row:
        backup_path = os.path.join(BACKUPS_DIR, row['filename'])
        if os.path.exists(backup_path):
            shutil.copy(backup_path, db.DB_PATH)
            flash("Database successfully restored to selected checkpoint.", "success")
        else:
            flash("Backup file not found on disk.", "error")
    else:
        flash("Checkpoint log record not found.", "error")
        
    return redirect(url_for('settings_page'))

# Backup: Delete local checkpoint file
@app.route('/backup/delete_local/<int:backup_id>')
def backup_delete_local(backup_id):
    if not db.DB_PATH:
        flash("Deleting local checkpoints is only supported in SQLite mode.", "error")
        return redirect(url_for('settings_page'))
    conn = db.get_db()
    row = conn.execute("SELECT filename FROM backup_history WHERE id = ?;", (backup_id,)).fetchone()
    if row:
        backup_path = os.path.join(BACKUPS_DIR, row['filename'])
        if os.path.exists(backup_path):
            os.remove(backup_path)
        conn.execute("DELETE FROM backup_history WHERE id = ?;", (backup_id,))
        conn.commit()
        flash("Local backup file deleted.", "warning")
    conn.close()
    return redirect(url_for('settings_page'))


# User Profile
@app.route('/profile')
def profile_page():
    user = auth_db.get_user_by_id(session.get('user_id'))
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('login'))
    
    # Convert user to dict if it's a Row object
    user_data = dict(user) if hasattr(user, 'keys') else user
    
    return render_template('profile.html', user_info=user_data)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    user_id = session.get('user_id')
    if not user_id:
        flash("User not authenticated.", "error")
        return redirect(url_for('login'))
        
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    full_name = request.form.get('full_name', '').strip()
    
    if not username or not email:
        flash("Username and Email are required fields.", "error")
        return redirect(url_for('profile_page'))
        
    # Input validation (basic check)
    if not re.match(r'^[\w.@+-]+$', username):
        flash("Username can only contain letters, numbers, and @/./+/-/_ characters.", "error")
        return redirect(url_for('profile_page'))
        
    if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for('profile_page'))
        
    success, message = auth_db.update_user_profile(user_id, username, email, full_name)
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
        
    return redirect(url_for('profile_page'))

@app.route('/change_password', methods=['POST'])
def change_password():
    user_id = session.get('user_id')
    if not user_id:
        flash("User not authenticated.", "error")
        return redirect(url_for('login'))
    
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    user = auth_db.get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('login'))
    
    # Verify current password
    if not auth_db.verify_password(current_password, user['password_hash']):
        flash("Current password is incorrect.", "error")
        return redirect(url_for('profile_page'))
    
    # Check if passwords match
    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(url_for('profile_page'))
    
    # Validate password
    valid, message = auth_db.validate_password(new_password)
    if not valid:
        flash(message, "error")
        return redirect(url_for('profile_page'))
    
    # Update password
    auth_db.update_password(user_id, new_password)
    flash("Password updated successfully.", "success")
    return redirect(url_for('profile_page'))

@app.teardown_appcontext
def teardown_db(exception):
    from flask import g
    db_conn = g.pop('_database_connection', None)
    if db_conn is not None:
        db_conn.real_close()

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    tb = traceback.format_exc()
    return f"<h1>Internal Server Error</h1><pre>{tb}</pre>", 500

@app.route('/test_version')
def test_version():
    return "version_debug_3a22277_and_1bd59be"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
