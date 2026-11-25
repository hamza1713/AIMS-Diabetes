"""
Notification Endpoints
======================
Notifications are generated server-side (welcome, out-of-range glucose alerts,
goal achievements, risk results).

  GET  /notifications?unread_only=&limit=   -> {items, unread_count}
  POST /notifications/mark-all-read         -> {updated}
  POST /notifications/{id}/read             -> NotificationResponse
  DELETE /notifications/{id}
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.models.db_models import Notification
from app.models.domain import NotificationResponse
from app.services.tracking_service import notification_out

router = APIRouter(prefix="/notifications")


def unread_count(db: Session, user_id: str) -> int:
    return db.query(Notification).filter(Notification.user_id == user_id, Notification.read.is_(False)).count()


@router.get("", summary="List Notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.read.is_(False))
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return {"items": [notification_out(n) for n in rows], "unread_count": unread_count(db, user_id)}


@router.post("/mark-all-read", summary="Mark All Notifications Read")
def mark_all_read(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read.is_(False))
        .update({Notification.read: True}, synchronize_session=False)
    )
    db.commit()
    return {"updated": updated}


def _get(db: Session, nid: int, user_id: str) -> Notification:
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return n


@router.post("/{notification_id}/read", response_model=NotificationResponse, summary="Mark One Notification Read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    n = _get(db, notification_id, user_id)
    n.read = True
    db.commit()
    db.refresh(n)
    return notification_out(n)


@router.delete("/{notification_id}", status_code=204, summary="Delete Notification")
def delete_notification(notification_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    db.delete(_get(db, notification_id, user_id))
    db.commit()
