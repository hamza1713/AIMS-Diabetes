"""
API v1 Router Aggregator
========================
Combines all modular endpoints into the primary API v1 router.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    health,
    llm,
    chat,
    papers,
    patient,
    risk,
    auth,
    users,
    exercise,
    water,
    medications,
    notifications,
    dashboard,
    analytics,
    vision,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health & Diagnostics"])
api_router.include_router(auth.router, tags=["Authentication"])
api_router.include_router(users.router, tags=["User Profile & Preferences"])
api_router.include_router(dashboard.router, tags=["Home Dashboard"])
api_router.include_router(llm.router, tags=["LLM Provider Management"])
api_router.include_router(chat.router, tags=["RAG Chat & Streaming"])
api_router.include_router(papers.router, tags=["Research Papers & Ingestion"])
api_router.include_router(patient.router, tags=["Patient Longitudinal Tracking"])
api_router.include_router(exercise.router, tags=["Exercise Tracking"])
api_router.include_router(water.router, tags=["Water Intake"])
api_router.include_router(medications.router, tags=["Medications"])
api_router.include_router(vision.router, tags=["Vision AI"])
api_router.include_router(risk.router, tags=["Clinical Risk Screening"])
api_router.include_router(analytics.router, tags=["Analytics & Reports"])
api_router.include_router(notifications.router, tags=["Notifications"])
