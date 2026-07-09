from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default='user')
    full_name = Column(String(120))
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String(50), nullable=False)
    last_login_at = Column(String(50))

class Invitation(Base):
    __tablename__ = 'invitations'
    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False)
    token_hash = Column(String(255), nullable=False)
    token = Column(String(255))
    created_at = Column(String(50), nullable=False)
    expires_at = Column(String(50), nullable=False)
    used_at = Column(String(50))
    cancelled_at = Column(String(50))
    status = Column(String(20), nullable=False, default='pending')
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))

class PasswordReset(Base):
    __tablename__ = 'password_resets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash = Column(String(255), nullable=False)
    created_at = Column(String(50), nullable=False)
    expires_at = Column(String(50), nullable=False)
    used_at = Column(String(50))

class Semester(Base):
    __tablename__ = 'semesters'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), nullable=False)
    start_date = Column(String(20), nullable=False)
    end_date = Column(String(20))
    target = Column(Float, default=75.0)
    working_days = Column(String(50), default='0,1,2,3,4')
    notes = Column(Text)

class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(50))
    faculty = Column(String(100))
    credits = Column(Integer, default=1)

class TimetableVersion(Base):
    __tablename__ = 'timetable_versions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    version_name = Column(String(100), nullable=False)
    effective_date = Column(String(20), nullable=False)
    end_date = Column(String(20))

class TimetableEntry(Base):
    __tablename__ = 'timetable_entries'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    version_id = Column(Integer, ForeignKey('timetable_versions.id', ondelete='CASCADE'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(String(20), nullable=False)
    end_time = Column(String(20), nullable=False)
    room = Column(String(50))
    notes = Column(Text)

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    date = Column(String(20), nullable=False)
    time = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)  # 'attended', 'missed'
    version_id = Column(Integer, ForeignKey('timetable_versions.id', ondelete='SET NULL'))
    notes = Column(Text)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'subject_id', 'date', 'time', name='uix_user_subject_date_time'),
    )

class Holiday(Base):
    __tablename__ = 'holidays'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    date = Column(String(20), nullable=False)
    reason = Column(String(255), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'semester_id', 'date', name='uix_user_semester_holiday_date'),
    )

class NoClassDay(Base):
    __tablename__ = 'no_class_days'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    date = Column(String(20), nullable=False)
    reason = Column(String(50), nullable=False)
    custom_description = Column(Text)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'semester_id', 'date', name='uix_user_semester_noclass_date'),
    )

class Setting(Base):
    __tablename__ = 'settings'
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    key = Column(String(100), primary_key=True)
    value = Column(Text)

class BackupHistory(Base):
    __tablename__ = 'backup_history'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    backup_time = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)

class CancelledClass(Base):
    __tablename__ = 'cancelled_classes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    date = Column(String(20), nullable=False)
    reason = Column(Text)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'subject_id', 'date', name='uix_user_subject_cancelled_date'),
    )

class ExtraClassDay(Base):
    __tablename__ = 'extra_class_days'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    semester_id = Column(Integer, ForeignKey('semesters.id', ondelete='CASCADE'), nullable=False)
    date = Column(String(20), nullable=False)
    day_to_follow = Column(Integer, nullable=False)
    reason = Column(Text)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'semester_id', 'date', name='uix_user_semester_extra_date'),
    )
