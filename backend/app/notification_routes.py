from fastapi import APIRouter, Depends, HTTPException, Header
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal
from sqlalchemy.future import select
from sqlalchemy import desc, func, text
import logging
import html
from pydantic import BaseModel, Extra, validator

from .database import AsyncSessionLocal, get_db
from .models import UserNotification, User, InfrastructureRequest, TerraformState
from .utils import normalize_resource_ids, unified_notification_handler, get_current_user
from .config import API_TOKEN
from .db_helpers import get_user_email_by_request_sync

logger = logging.getLogger(__name__)
router = APIRouter()

# Thread-safe processed requests tracking
from threading import Lock
from collections import deque

processed_requests = deque(maxlen=1000)
processed_requests_lock = Lock()

class DeployedPayload(BaseModel, extra=Extra.ignore):
    """Payload for deployed infrastructure notifications"""
    request_identifier: str
    status: Literal["deployed"] = "deployed"
    instance_id: Optional[str] = None
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    ip_address: Optional[str] = None
    ip_type: Optional[str] = None
    console_url: Optional[str] = None
    terraform_state: Optional[str] = None
    created_at: Optional[str] = None
    cloud_provider: Optional[str] = None
    environment: Optional[str] = None
    
    @validator('request_identifier', 'instance_id', 'console_url', pre=True)
    def sanitize_strings(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize string inputs to prevent XSS attacks"""
        if v is not None:
            return html.escape(str(v))
        return v

class FailedPayload(BaseModel, extra=Extra.ignore):
    """Payload for failed infrastructure notifications"""
    request_identifier: str
    status: Literal["failed"] = "failed"
    error_message: Optional[str] = None

class PRCreatedPayload(BaseModel, extra=Extra.ignore):
    """Payload for PR created notifications"""
    request_identifier: str
    status: Literal["pr_created"] = "pr_created"
    pr_number: Optional[int] = None

class DestroyedPayload(BaseModel, extra=Extra.ignore):
    """Payload for destroyed infrastructure notifications"""
    request_identifier: str
    status: Literal["destroyed"] = "destroyed"
    destroyed_at: Optional[str] = None

def verify_github_token(authorization: Optional[str] = Header(None)) -> bool:
    """Verify GitHub webhook token"""
    if not authorization:
        raise HTTPException(
            status_code=401, 
            detail="Authorization header required"
        )
    
    try:
        token_type, token = authorization.split(" ", 1)
    except ValueError:
        raise HTTPException(
            status_code=401, 
            detail="Invalid authorization header"
        )
    
    if token_type.lower() != "bearer":
        raise HTTPException(
            status_code=401, 
            detail="Invalid token type"
        )
    
    if not API_TOKEN or token != API_TOKEN:
        raise HTTPException(
            status_code=401, 
            detail="Invalid API token"
        )
    
    return True

@router.get("/api/notifications")
async def get_user_notifications(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
    unread_only: bool = False
):
    try:
        async with AsyncSessionLocal() as db:
            query = (
                select(UserNotification)
                .where(UserNotification.user_id == current_user.id)
                .order_by(desc(UserNotification.created_at))
            )
            if unread_only:
                query = query.where(UserNotification.is_read.is_(False))
            query = query.limit(limit)
            # Single query to get both notifications and count
            result = await db.execute(query)
            notifications = result.scalars().all()
            
            # Calculate unread count from fetched notifications if unread_only is False
            if unread_only:
                unread_count = len(notifications)
            else:
                unread_count = sum(1 for n in notifications if not n.is_read)
            notification_responses = []
            for notif in notifications:
                deployment_details = notif.deployment_details or {}
                notification_responses.append({
                    "id": str(notif.id),
                    "title": notif.title,
                    "message": notif.message,
                    "status": notif.status,
                    "deployment_details": deployment_details,
                    "is_read": notif.is_read,
                    "created_at": notif.created_at.isoformat(),
                    "read_at": notif.read_at.isoformat() if notif.read_at else None
                })
            return {
                "notifications": notification_responses,
                "unread_count": unread_count or 0,
                "total_count": len(notification_responses)
            }
    except Exception as e:
        logger.error("Failed to get notifications", exc_info=True)
        return {"notifications": [], "unread_count": 0, "total_count": 0}

@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user)
):
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserNotification)
                .where(
                    UserNotification.id == notification_id,
                    UserNotification.user_id == current_user.id
                )
            )
            notification = result.scalar_one_or_none()
            if not notification:
                return {"error": "Notification not found"}
            notification.is_read = True
            notification.read_at = datetime.now()
            await db.commit()
            return {"message": "Notification marked as read"}
    except Exception as e:
        logger.error("Failed to mark notification as read", exc_info=True)
        return {"error": "Failed to update notification"}

@router.post("/api/notifications/mark-all-read")
async def mark_all_notifications_read(current_user: User = Depends(get_current_user)):
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserNotification)
                .where(UserNotification.user_id == current_user.id,
                       UserNotification.is_read.is_(False))
            )
            notifications = result.scalars().all()
            for notification in notifications:
                notification.is_read = True
                notification.read_at = datetime.now()
            await db.commit()
            return {"message": f"Marked {len(notifications)} notifications as read"}
    except Exception as e:
        logger.error("Failed to mark all notifications as read", exc_info=True)
        return {"error": "Failed to update notifications"}

@router.get("/api/notifications/unread-count")
async def get_unread_count(current_user: User = Depends(get_current_user)):
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count(UserNotification.id))
                .where(UserNotification.user_id == current_user.id,
                       UserNotification.is_read.is_(False))
            )
            unread_count = result.scalar()
            return {"unread_count": unread_count or 0}
    except Exception as e:
        logger.error("Failed to get unread count", exc_info=True)
        return {"unread_count": 0}

@router.get("/api/notifications/test/{user_email}")
async def test_get_notifications_by_email(user_email: str):
    """Test endpoint to check notifications for a specific user email"""
    try:
        async with AsyncSessionLocal() as db:
            # Get user by email
            user_result = await db.execute(select(User).where(User.email == user_email))
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {"error": "User not found", "email": user_email}
            
            # Get notifications for this user
            result = await db.execute(
                select(UserNotification)
                .where(UserNotification.user_id == user.id)
                .order_by(desc(UserNotification.created_at))
                .limit(10)
            )
            notifications = result.scalars().all()
            
            notification_list = []
            for notif in notifications:
                notification_list.append({
                    "id": str(notif.id),
                    "title": notif.title,
                    "message": notif.message,
                    "status": notif.status,
                    "deployment_details": notif.deployment_details,
                    "is_read": notif.is_read,
                    "created_at": notif.created_at.isoformat()
                })
            
            return {
                "user_email": user_email,
                "user_id": str(user.id),
                "notifications_count": len(notification_list),
                "notifications": notification_list
            }
            
    except Exception as e:
        logger.error("Test endpoint error", exc_info=True)
        return {"error": "Internal server error", "email": user_email}

@router.post("/api/notifications/clear-all")
async def clear_all_notifications(current_user: User = Depends(get_current_user)):
    """Clear all notifications for current user"""
    try:
        async with AsyncSessionLocal() as db:
            # Delete all notifications for this user in batch
            from sqlalchemy import delete
            delete_stmt = delete(UserNotification).where(
                UserNotification.user_id == current_user.id
            )
            await db.execute(delete_stmt)
            notifications_count = await db.execute(
                select(func.count(UserNotification.id)).where(UserNotification.user_id == current_user.id)
            )
            count = notifications_count.scalar() or 0
            
            await db.commit()
            
            return {"message": f"Cleared {count} notifications", "cleared_count": count}
            
    except Exception as e:
        logger.error("Clear notifications error", exc_info=True)
        return {"error": "Failed to clear notifications"}

@router.post("/api/notifications/create-test")
async def create_test_notification_endpoint():
    """Create a test notification for debugging"""
    try:
        async with AsyncSessionLocal() as db:
            # Get user
            user_result = await db.execute(select(User).where(User.email == "manoharkadimisetti3@gmail.com"))
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {"error": "User not found"}
            
            # Create test notification
            notification = UserNotification(
                user_id=user.id,
                request_id=None,
                notification_type="deployment",
                title="Test Infrastructure Ready - abc123",
                message="Your test infrastructure abc123 is ready! Instance i-test123 is running with IP 54.123.45.67.",
                status="deployed",
                deployment_details={
                    "instance_id": "i-test123",
                    "ip_address": "54.123.45.67",
                    "ip_type": "public",
                    "console_url": "https://console.aws.amazon.com/ec2/test"
                },
                is_read=False
            )
            
            db.add(notification)
            await db.commit()
            
            return {"message": "Test notification created successfully", "user_id": str(user.id)}
            
    except Exception as e:
        logger.error(f"Create test notification error: {e}")
        return {"error": str(e)}

# Notification endpoint moved to infrastructure.py to avoid route conflicts