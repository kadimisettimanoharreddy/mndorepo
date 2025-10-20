from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta
import secrets
import logging
from .database import get_db
from .models import User, EnvironmentApproval
from .utils import get_current_user
from .email_service import send_environment_approval_email, send_access_granted_email, send_access_denied_email
from .websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/environment", tags=["environment"])

@router.post("/request-access")
async def request_environment_access(environment: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        if current_user.environment_access.get(environment):
            raise HTTPException(status_code=400, detail=f"You already have access to {environment} environment")
        result = await db.execute(select(EnvironmentApproval).where(EnvironmentApproval.user_id == current_user.id, EnvironmentApproval.environment == environment, EnvironmentApproval.status == "pending"))
        existing_request = result.scalar_one_or_none()
        if existing_request:
            raise HTTPException(status_code=400, detail="You already have a pending request for this environment")
        approval_token = secrets.token_urlsafe(32)
        approval_request = EnvironmentApproval(user_id=current_user.id, environment=environment, approval_token=approval_token, manager_email=current_user.manager_email, status="pending")
        db.add(approval_request)
        await db.commit()
        await send_environment_approval_email(manager_email=current_user.manager_email, user_name=current_user.name, user_department=current_user.department, environment=environment, approval_token=approval_token)
        logger.info(f"Environment access requested: {current_user.email} -> {environment}")
        return {"message": f"Access request for {environment} environment sent to your manager", "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error requesting environment access: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to process request")

@router.get("/approve/{approval_token}")
async def approve_environment_access(approval_token: str, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(EnvironmentApproval, User).join(User).where(EnvironmentApproval.approval_token == approval_token))
        approval_data = result.first()
        if not approval_data:
            return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Invalid Request</h2><p>This approval link is invalid or has been removed.</p></div></body></html>")
        approval, user = approval_data
        if approval.status == "approved":
            logger.info(f"Duplicate approval click for {user.email} -> {approval.environment}")
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#27ae60; color:white; padding:20px; border-radius:5px;'><h2>Already Approved</h2><p>Access to <strong>{approval.environment.upper()}</strong> was already approved for <strong>{user.name}</strong>.</p><p style='font-size:14px; opacity:0.8;'>Approved on: {approval.approved_at.strftime('%B %d, %Y at %I:%M %p')}</p></div><script>setTimeout(() => window.close(), 5000);</script></body></html>")
        elif approval.status == "denied":
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Previously Denied</h2><p>This request was already denied and cannot be approved.</p></div></body></html>")
        elif approval.status == "expired":
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#f39c12; color:white; padding:20px; border-radius:5px;'><h2>Request Expired</h2><p>This approval request has expired.</p></div></body></html>")
        if approval.status == "pending":
            if approval.requested_at < datetime.utcnow() - timedelta(hours=24):
                approval.status = "expired"
                await db.commit()
                return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#f39c12; color:white; padding:20px; border-radius:5px;'><h2>Request Expired</h2><p>This approval request has expired (older than 24 hours).</p></div></body></html>")
            approval.status = "approved"
            approval.approved_at = datetime.utcnow()
            approval.expires_at = datetime.utcnow() + timedelta(hours=48)
            ua = dict(user.environment_access or {})
            ua[approval.environment] = True
            user.environment_access = ua
            ue = dict(user.environment_expiry or {})
            ue[approval.environment] = approval.expires_at.isoformat()
            user.environment_expiry = ue
            await db.commit()
            await send_access_granted_email(user_email=user.email, user_name=user.name, environment=approval.environment, approved_by=approval.manager_email)
            # Send approval notification (popup only - no database storage)
            from .notification_handler import send_approval_notifications
            await send_approval_notifications(user.email, approval.environment, True)
            logger.info(f"Environment access approved: {user.email} -> {approval.environment} (expires: {approval.expires_at})")
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#27ae60; color:white; padding:20px; border-radius:5px;'><h2>✓ Access Approved</h2><p><strong>{user.name}</strong> now has access to <strong>{approval.environment.upper()}</strong>.</p><p style='font-size:14px; opacity:0.8;'>Access expires in 48 hours</p></div><script>setTimeout(() => window.close(), 5000);</script></body></html>")
        return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#6c757d; color:white; padding:20px; border-radius:5px;'><h2>Unknown Status</h2><p>Unable to process this request.</p></div></body></html>")
    except Exception as e:
        logger.error(f"Error approving access: {e}")
        await db.rollback()
        return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Error</h2><p>An error occurred processing this request.</p></div></body></html>")

@router.get("/deny/{approval_token}")
async def deny_environment_access(approval_token: str, reason: str = "Not specified", db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(EnvironmentApproval, User).join(User).where(EnvironmentApproval.approval_token == approval_token))
        approval_data = result.first()
        if not approval_data:
            return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Invalid Request</h2><p>This approval link is invalid or has been removed.</p></div></body></html>")
        approval, user = approval_data
        if approval.status == "denied":
            logger.info(f"Duplicate denial click for {user.email} -> {approval.environment}")
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Already Denied</h2><p>Access to <strong>{approval.environment.upper()}</strong> was already denied.</p></div><script>setTimeout(() => window.close(), 5000);</script></body></html>")
        elif approval.status == "approved":
            return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#f39c12; color:white; padding:20px; border-radius:5px;'><h2>Previously Approved</h2><p>This request was already approved and cannot be denied.</p></div></body></html>")
        if approval.status == "pending":
            approval.status = "denied"
            approval.approved_at = datetime.utcnow()
            await db.commit()
            await send_access_denied_email(user_email=user.email, user_name=user.name, environment=approval.environment, denied_by=approval.manager_email, reason=reason)
            
            from .notification_handler import send_approval_notifications
            await send_approval_notifications(user.email, approval.environment, False)
            logger.info(f"Environment access denied: {user.email} -> {approval.environment}")
            return HTMLResponse(f"<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>✗ Access Denied</h2><p>Access to <strong>{approval.environment.upper()}</strong> has been denied for <strong>{user.name}</strong>.</p></div><script>setTimeout(() => window.close(), 5000);</script></body></html>")
        return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#6c757d; color:white; padding:20px; border-radius:5px;'><h2>Unknown Status</h2><p>Unable to process this request.</p></div></body></html>")
    except Exception as e:
        logger.error(f"Error denying access: {e}")
        await db.rollback()
        return HTMLResponse("<html><body style='font-family: Arial; max-width:500px; margin:50px auto; text-align:center;'><div style='background:#e74c3c; color:white; padding:20px; border-radius:5px;'><h2>Error</h2><p>An error occurred processing this request.</p></div></body></html>")

@router.get("/my-requests")
async def get_my_environment_requests(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = await db.execute(select(EnvironmentApproval).where(EnvironmentApproval.user_id == current_user.id).order_by(EnvironmentApproval.requested_at.desc()))
        requests = result.scalars().all()
        return {"requests": [{"id": str(req.id), "environment": req.environment, "status": req.status, "requested_at": req.requested_at.isoformat(), "approved_at": req.approved_at.isoformat() if req.approved_at else None, "expires_at": req.expires_at.isoformat() if req.expires_at else None} for req in requests]}
    except Exception as e:
        logger.error(f"Error fetching environment requests: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch requests")
