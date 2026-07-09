# AttendX

A modern, responsive personal attendance tracker built with **Flask**, **SQLite**, **Bootstrap 5**, and **Chart.js**.

## Features

- **Dashboard** — Overall attendance %, subject breakdown, safe leaves, goal milestones, today's schedule, upcoming classes, charts
- **Semester Management** — Multiple semesters with mandatory start date and optional end date, working days, attendance targets
- **Timetable Versioning** — Upload Excel/CSV, manual entry, edit, duplicate, delete; effective-date versioning preserves history
- **Daily Attendance** — Mark attended/missed by checkbox (unchecked = missed)
- **Holidays & No-Class Days** — Excluded from attendance calculations
- **Calendar** — Color-coded monthly view with date detail modal
- **Predictions** — Scenario simulator, safe leave calculator, custom date-range analysis
- **Reports & Search** — Filter by date, subject, faculty, status; export CSV, Excel, PDF
- **Notifications** — Class reminders and attendance warnings
- **Backup** — Export/import database, automatic local backups, restore points
- **Settings** — Dark/light mode, date/time formats, custom goal milestones

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the application

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

### 3. Get started

On first launch, use the **Quick Start** wizard: enter a semester name, **start date** (required), and upload a timetable file (`.xlsx` or `.csv`).

## Timetable File Format

| Day | Subject | Start Time | End Time | Room | Faculty | Notes |
|-----|---------|------------|----------|------|---------|-------|
| Monday | Mathematics | 09:00 | 10:00 | A101 | Dr. Smith | |
| Tuesday | Physics | 10:00 | 11:00 | B205 | | |

- **Day**: Monday–Sunday (or Mon, Tue, etc.)
- **Times**: 24-hour (`09:00`) or 12-hour (`9:00 AM`)

## Semester Dates

- **Start date** is required when creating or editing a semester.
- **End date** is optional — leave blank for ongoing semesters. Predictions use a 1-year default horizon when no end date is set.

## Project Structure

```
AttendX/
├── app.py              # Flask routes and application logic
├── auth_db.py          # User authentication and registration database handler
├── database.py         # SQLite operations and calculations
├── schema.sql          # Database schema
├── requirements.txt    # Project dependencies
├── .env.example        # Reference file for environment variables
├── .gitignore          # Git ignore file (excludes DBs, venv, backups)
├── static/             # Static frontend assets (css, js, images)
│   └── css/style.css   # Curated premium theme styling
├── templates/          # Jinja2 HTML templates
└── scripts/            # Database migration and utility command-line scripts
    ├── check_databases.py
    ├── list_users.py
    ├── transfer_data.py
    └── transfer_main_to_user.py
```

## Environment Variables

Copy `.env.example` to `.env` and fill in:
- `SECRET_KEY`: Secret key for session signing.
- `DATABASE_DIR`: Path to the directory where SQLite database files (`auth.db`, `attendance.db`, and user-specific databases) should be stored. Excellent for mounting persistent disks on cloud platforms.
- `ADMIN_USERNAME`/`ADMIN_PASSWORD`: Default administrator credentials generated on first launch.
- `SMTP_*`: Optional email settings for reset password and registration invitation functionalities.

## Production Deployment on Render

1. **Create Web Service**:
   - Repository: Link your GitHub repository containing the application.
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`

2. **Database Persistence**:
   - Because SQLite databases are stored on disk, attach a **Persistent Disk** on Render (e.g. mounted at `/data`).
   - Set the Environment Variable `DATABASE_DIR=/data`. This guarantees your database files survive restarts and redeployments!

3. **Environment Configuration**:
   - Add the necessary env variables (like `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`) under Render's **Environment** tab.

## Database

All data is stored in SQLite databases inside `DATABASE_DIR` (defaults to the root directory). Use **Settings → Database Export** to back up, or enable automatic local backups on startup.

