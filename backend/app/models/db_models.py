from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ResearchPaper(Base):
    __tablename__ = "research_papers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    authors = Column(Text, nullable=True)
    journal = Column(String, nullable=True)
    publication_year = Column(Integer, index=True, nullable=True)
    doi = Column(String, unique=True, index=True, nullable=True)
    file_path = Column(String, nullable=False)
    file_hash = Column(String(64), index=True, nullable=True)
    page_count = Column(Integer, default=0)
    indexed = Column(Boolean, default=False)
    department = Column(String, default="General", nullable=True)
    access_roles = Column(String, default="clinical,research", nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    pages = relationship("PaperPage", back_populates="paper", cascade="all, delete-orphan")


class PaperPage(Base):
    __tablename__ = "paper_pages"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("research_papers.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    image_path = Column(String, nullable=True)
    has_tables = Column(Boolean, default=False)
    has_charts = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("ResearchPaper", back_populates="pages")


class GlucoseLog(Base):
    __tablename__ = "glucose_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, default="default_user")
    measurement_type = Column(String, nullable=False)  # Fasting, Postprandial, Random, HbA1c
    glucose_value = Column(Float, nullable=False)      # mg/dL or % for HbA1c
    notes = Column(Text, nullable=True)
    context = Column(String, nullable=True)            # "when": fasting, before_meal, after_meal, bedtime, random
    recorded_at = Column(DateTime, default=datetime.utcnow)  # reading time (UTC, naive)


class MealLog(Base):
    __tablename__ = "meal_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, default="default_user")
    meal_type = Column(String, nullable=False)        # Breakfast, Lunch, Dinner, Snack
    description = Column(Text, nullable=False, default="")
    carbs_grams = Column(Float, nullable=True)
    name = Column(String, nullable=True)
    calories = Column(Float, nullable=True)
    protein_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)  # exposed to clients as "logged_at"


class RiskAssessmentLog(Base):
    __tablename__ = "risk_assessment_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, default="default_user")
    assessment_type = Column(String, nullable=False)  # ADA, FINDRISC
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)        # Low, Moderate, High, Very High
    answers_json = Column(JSON, nullable=True)
    recommendations = Column(Text, nullable=True)
    assessed_at = Column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    """
    Persists per-user conversation turns to SQLite for history durability.
    Loaded into ConversationMemory on first access and used to seed the
    in-memory rolling window after a server restart.
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)   # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Composite index for efficient "fetch last N messages for user X" queries
    __table_args__ = (
        Index("ix_chat_messages_user_created", "user_id", "created_at"),
    )


# -----------------------------------------------------------------------------
# Mobile app (AIMS-Diabetes) tables
# Every per-user table keys on user_id = str(User.id) (or a legacy string id
# such as "default_user" when DEBUG header auth is used).
# -----------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False, default="")
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)            # male, female, other
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    diabetes_type = Column(String, nullable=True)     # type1, type2, gestational, prediabetes, none
    photo_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String, primary_key=True)
    glucose_unit = Column(String, default="mg/dL")    # mg/dL | mmol/L
    weight_unit = Column(String, default="kg")        # kg | lb
    height_unit = Column(String, default="cm")        # cm | ft
    language = Column(String, default="en")
    theme = Column(String, default="system")          # light | dark | system
    medication_reminders = Column(Boolean, default=True)
    glucose_alerts = Column(Boolean, default=True)
    daily_tips = Column(Boolean, default=True)
    water_goal_ml = Column(Integer, default=2000)
    weekly_exercise_goal_min = Column(Integer, default=150)
    daily_calorie_goal = Column(Integer, default=2000)
    daily_carbs_goal_g = Column(Integer, default=200)
    target_glucose_min = Column(Float, default=70.0)
    target_glucose_max = Column(Float, default=180.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExerciseLog(Base):
    __tablename__ = "exercise_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    activity = Column(String, nullable=False)          # walking, running, cycling, ...
    duration_min = Column(Integer, nullable=False)
    calories = Column(Float, nullable=True)
    intensity = Column(String, nullable=True)          # low, moderate, high
    notes = Column(Text, nullable=True)
    performed_at = Column(DateTime, default=datetime.utcnow, index=True)


class WaterLog(Base):
    __tablename__ = "water_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    amount_ml = Column(Integer, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    dosage = Column(String, nullable=True)             # "500 mg", "10 units"
    form = Column(String, nullable=True)               # tablet, injection, capsule, ...
    frequency = Column(String, nullable=True)          # once_daily, twice_daily, ...
    times = Column(JSON, nullable=True)                # ["08:00", "20:00"] local times
    instructions = Column(Text, nullable=True)         # "with food"
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doses = relationship("MedicationDose", back_populates="medication", cascade="all, delete-orphan")


class MedicationDose(Base):
    __tablename__ = "medication_doses"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False, index=True)
    user_id = Column(String, index=True, nullable=False)
    scheduled_time = Column(String, nullable=True)     # "08:00" slot this dose fulfils
    status = Column(String, default="taken")           # taken | skipped
    taken_at = Column(DateTime, default=datetime.utcnow, index=True)

    medication = relationship("Medication", back_populates="doses")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    type = Column(String, default="info")              # info, alert, reminder, achievement
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
