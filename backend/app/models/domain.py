from pydantic import BaseModel, Field, ConfigDict, EmailStr, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

# --- Paper Schemas ---
class PaperCreate(BaseModel):
    title: str
    authors: Optional[str] = None
    journal: Optional[str] = None
    publication_year: Optional[int] = None
    doi: Optional[str] = None
    file_path: str

class PaperResponse(BaseModel):
    id: int
    title: str
    authors: Optional[str]
    journal: Optional[str]
    publication_year: Optional[int]
    doi: Optional[str]
    file_path: str
    page_count: int
    indexed: bool
    created_at: datetime
    image_url: Optional[str] = None
    department: Optional[str] = "General"
    access_roles: Optional[str] = "clinical,research"

    model_config = ConfigDict(from_attributes=True)

# --- Retrieval Schemas ---
class SearchQuery(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)

class SearchResultPage(BaseModel):
    paper_id: Optional[int]
    paper_title: str
    page_number: int
    score: float
    image_path: Optional[str]
    authors: Optional[str]
    journal: Optional[str]
    publication_year: Optional[int]

# --- Health Schemas ---

# Figma "When" values -> legacy measurement_type
GLUCOSE_WHEN_TO_TYPE = {
    "fasting": "Fasting",
    "before_meal": "Random",
    "after_meal": "Postprandial",
    "bedtime": "Random",
    "random": "Random",
}
GLUCOSE_TYPE_TO_WHEN = {"Fasting": "fasting", "Postprandial": "after_meal", "Random": "random"}


class GlucoseLogCreate(BaseModel):
    """
    Either ``measurement_type`` (legacy: Fasting, Postprandial, Random, HbA1c) or
    ``when`` (fasting, before_meal, after_meal, bedtime, random) may be sent; the
    other is derived. ``recorded_at`` is the reading time (defaults to now).
    """
    measurement_type: Optional[str] = None
    glucose_value: float = Field(gt=0)
    notes: Optional[str] = None
    when: Optional[Literal["fasting", "before_meal", "after_meal", "bedtime", "random"]] = None
    recorded_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _derive_type(self):
        if not self.measurement_type:
            self.measurement_type = GLUCOSE_WHEN_TO_TYPE.get(self.when or "random", "Random")
        if not self.when and self.measurement_type in GLUCOSE_TYPE_TO_WHEN:
            self.when = GLUCOSE_TYPE_TO_WHEN[self.measurement_type]
        return self


class GlucoseLogResponse(BaseModel):
    id: int
    user_id: str
    measurement_type: str
    glucose_value: float
    notes: Optional[str] = None
    when: Optional[str] = None
    status: Optional[str] = None  # low | normal | high (vs. target range)
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RiskAssessmentInput(BaseModel):
    age: int
    gender: str
    bmi: float
    family_history: bool
    high_blood_pressure: bool
    physical_activity: str
    ethnicity: Optional[str] = None

class RiskAssessmentResult(BaseModel):
    assessment_type: str
    risk_score: float
    risk_level: str
    summary: str
    recommendations: List[str]

# --- Chat & Provider Schemas ---
class ChatQueryRequest(BaseModel):
    query: str
    user_id: str = "default_user"  # legacy / DEBUG only — the Bearer token user wins
    provider: Optional[str] = None

class ProviderUpdateRequest(BaseModel):
    provider: str

class MealLogCreate(BaseModel):
    meal_type: str                      # Breakfast, Lunch, Dinner, Snack
    description: str = ""
    carbs_grams: Optional[float] = Field(default=None, ge=0)
    name: Optional[str] = None
    calories: Optional[float] = Field(default=None, ge=0)
    protein_g: Optional[float] = Field(default=None, ge=0)
    fat_g: Optional[float] = Field(default=None, ge=0)
    logged_at: Optional[datetime] = None


class MealLogResponse(BaseModel):
    id: int
    user_id: str
    meal_type: str
    name: Optional[str] = None
    description: str = ""
    carbs_grams: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    logged_at: datetime


class NutritionTotals(BaseModel):
    calories: float = 0
    carbs_g: float = 0
    protein_g: float = 0
    fat_g: float = 0
    meal_count: int = 0


class MealDailyTotals(BaseModel):
    date: str
    totals: NutritionTotals
    goals: Dict[str, int]
    by_meal_type: Dict[str, NutritionTotals]


# --- Auth & User Schemas ---

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserProfile(BaseModel):
    id: int
    email: str
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    diabetes_type: Optional[str] = None
    photo_url: Optional[str] = None
    bmi: Optional[float] = None
    bmi_category: Optional[str] = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Optional[UserProfile] = None


class UserProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    age: Optional[int] = Field(default=None, ge=1, le=120)
    gender: Optional[Literal["male", "female", "other"]] = None
    height_cm: Optional[float] = Field(default=None, gt=30, lt=272)
    weight_kg: Optional[float] = Field(default=None, gt=2, lt=500)
    diabetes_type: Optional[Literal["type1", "type2", "gestational", "prediabetes", "none", "other"]] = None
    photo_url: Optional[str] = Field(default=None, max_length=2048)


class UserPreferencesSchema(BaseModel):
    glucose_unit: Literal["mg/dL", "mmol/L"] = "mg/dL"
    weight_unit: Literal["kg", "lb"] = "kg"
    height_unit: Literal["cm", "ft"] = "cm"
    language: str = Field(default="en", max_length=10)
    theme: Literal["light", "dark", "system"] = "system"
    medication_reminders: bool = True
    glucose_alerts: bool = True
    daily_tips: bool = True
    water_goal_ml: int = Field(default=2000, ge=250, le=10000)
    weekly_exercise_goal_min: int = Field(default=150, ge=0, le=3000)
    daily_calorie_goal: int = Field(default=2000, ge=500, le=10000)
    daily_carbs_goal_g: int = Field(default=200, ge=0, le=1000)
    target_glucose_min: float = Field(default=70.0, ge=40, le=200)
    target_glucose_max: float = Field(default=180.0, ge=80, le=400)

    model_config = ConfigDict(from_attributes=True)


class UserPreferencesUpdate(BaseModel):
    glucose_unit: Optional[Literal["mg/dL", "mmol/L"]] = None
    weight_unit: Optional[Literal["kg", "lb"]] = None
    height_unit: Optional[Literal["cm", "ft"]] = None
    language: Optional[str] = Field(default=None, max_length=10)
    theme: Optional[Literal["light", "dark", "system"]] = None
    medication_reminders: Optional[bool] = None
    glucose_alerts: Optional[bool] = None
    daily_tips: Optional[bool] = None
    water_goal_ml: Optional[int] = Field(default=None, ge=250, le=10000)
    weekly_exercise_goal_min: Optional[int] = Field(default=None, ge=0, le=3000)
    daily_calorie_goal: Optional[int] = Field(default=None, ge=500, le=10000)
    daily_carbs_goal_g: Optional[int] = Field(default=None, ge=0, le=1000)
    target_glucose_min: Optional[float] = Field(default=None, ge=40, le=200)
    target_glucose_max: Optional[float] = Field(default=None, ge=80, le=400)


# --- Exercise / Water ---

class ExerciseLogCreate(BaseModel):
    activity: str = Field(min_length=1, max_length=80)
    duration_min: int = Field(gt=0, le=1440)
    calories: Optional[float] = Field(default=None, ge=0)
    intensity: Optional[Literal["low", "moderate", "high"]] = None
    notes: Optional[str] = None
    performed_at: Optional[datetime] = None


class ExerciseLogResponse(BaseModel):
    id: int
    activity: str
    duration_min: int
    calories: Optional[float] = None
    intensity: Optional[str] = None
    notes: Optional[str] = None
    performed_at: datetime


class WaterLogCreate(BaseModel):
    amount_ml: int = Field(gt=0, le=5000)
    recorded_at: Optional[datetime] = None


class WaterLogResponse(BaseModel):
    id: int
    amount_ml: int
    recorded_at: datetime


# --- Medications ---

_TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


def _validate_times(v: List[str]) -> List[str]:
    import re
    for t in v:
        if not re.match(_TIME_RE, t):
            raise ValueError(f"Invalid time '{t}', expected HH:MM (24h).")
    return sorted(set(v))


class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dosage: Optional[str] = Field(default=None, max_length=60)
    form: Optional[str] = Field(default=None, max_length=40)
    frequency: Optional[str] = Field(default="once_daily", max_length=40)
    times: List[str] = Field(default_factory=list, description="Local HH:MM dose times")
    instructions: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: bool = True

    @field_validator("times")
    @classmethod
    def _check_times(cls, v: List[str]) -> List[str]:
        return _validate_times(v)


class MedicationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    dosage: Optional[str] = Field(default=None, max_length=60)
    form: Optional[str] = Field(default=None, max_length=40)
    frequency: Optional[str] = Field(default=None, max_length=40)
    times: Optional[List[str]] = None
    instructions: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: Optional[bool] = None

    @field_validator("times")
    @classmethod
    def _check_times(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return None if v is None else _validate_times(v)


class MedicationResponse(BaseModel):
    id: int
    name: str
    dosage: Optional[str] = None
    form: Optional[str] = None
    frequency: Optional[str] = None
    times: List[str] = []
    instructions: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: bool = True
    created_at: datetime


class MedicationDoseCreate(BaseModel):
    scheduled_time: Optional[str] = Field(default=None, pattern=_TIME_RE)
    status: Literal["taken", "skipped"] = "taken"
    taken_at: Optional[datetime] = None


class MedicationDoseResponse(BaseModel):
    id: int
    medication_id: int
    scheduled_time: Optional[str] = None
    status: str
    taken_at: datetime


# --- Notifications ---

class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    body: Optional[str] = None
    read: bool
    created_at: datetime


# --- CDC Prediabetes Risk Test ---

class CDCRiskInput(BaseModel):
    """
    CDC / ADA 7-question prediabetes risk test. Supply either ``bmi`` or
    ``weight_kg`` + ``height_cm`` (falls back to the saved profile when omitted).
    """
    age: int = Field(ge=1, le=120)
    sex: Literal["male", "female"]
    gestational_diabetes: bool = False
    family_history: bool
    high_blood_pressure: bool
    physically_active: bool
    weight_kg: Optional[float] = Field(default=None, gt=2, lt=500)
    height_cm: Optional[float] = Field(default=None, gt=30, lt=272)
    bmi: Optional[float] = Field(default=None, gt=5, lt=120)
    asian_american: bool = False  # CDC uses lower BMI cut-offs for Asian Americans
    save: bool = True


class CDCRiskFactor(BaseModel):
    key: str
    question: str
    answer: str
    points: int
    max_points: int


class CDCRiskResult(BaseModel):
    id: Optional[int] = None
    assessment_type: str = "CDC_PREDIABETES"
    score: int
    max_score: int = 11
    risk_level: str           # Low | Moderate | High
    at_risk: bool             # score >= 5 (CDC threshold)
    bmi: Optional[float] = None
    factors: List[CDCRiskFactor]
    summary: str
    recommendations: List[str]
    assessed_at: datetime


# --- Vision AI ---

class VisionFoodItem(BaseModel):
    name: str
    portion: Optional[str] = None
    carbs_g: Optional[float] = None
    calories: Optional[float] = None


class VisionMealAnalysis(BaseModel):
    food: str
    confidence: float          # 0..1
    items: List[VisionFoodItem] = []
    carbs_g: float
    calories: float
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    glycemic_index: Optional[float] = None
    glycemic_load: float
    glycemic_load_category: str   # low (<=10) | medium (11-19) | high (>=20)
    advice: Optional[str] = None
    model: Optional[str] = None
    saved_meal_id: Optional[int] = None
