from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer
from sqlalchemy.future import select
import json

from .config import JWT_SECRET, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from .database import AsyncSessionLocal
from .models import User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def verify_jwt_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(token: str = Depends(security)) -> User:
    import logging
    logger = logging.getLogger(__name__)
    
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials"
    )
    
    try:
        logger.info(f"Validating token: {token.credentials[:20]}...")
        payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        logger.info(f"Token decoded for email: {email}")
        
        if email is None:
            logger.error("No email found in token payload")
            raise credentials_exception
            
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error in token validation: {e}")
        raise HTTPException(status_code=500, detail="Token validation error")

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            
            if user is None:
                logger.error(f"User not found for email: {email}")
                raise credentials_exception
                
            logger.info(f"User found: {user.email}")
            return user
            
    except Exception as e:
        logger.error(f"Database error in get_current_user: {e}")
        raise HTTPException(status_code=500, detail="Database error")

def extract_clean_value(tf_output: Any) -> str:
    """Extract and clean terraform output values"""
    if tf_output is None:
        return ""
    
    if isinstance(tf_output, dict):
        if "value" in tf_output:
            value = tf_output["value"]
            return str(value).strip() if value is not None else ""
        if all(key in tf_output for key in ["sensitive", "type", "value"]):
            return str(tf_output["value"]).strip()
        return ""
    
    if isinstance(tf_output, str):
        # Try to parse JSON string (common in resource_ids)
        try:
            import json
            parsed = json.loads(tf_output)
            if isinstance(parsed, dict) and "value" in parsed:
                return str(parsed["value"]).strip()
        except (json.JSONDecodeError, ValueError):
            pass
        return tf_output.strip()
    
    return str(tf_output).strip() if tf_output else ""

def extract_terraform_value(tf_output: Any) -> Any:
    return extract_clean_value(tf_output)

def sanitize_deployment_details(details: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    
    sanitized = {}
    
    # Include Instance ID, IP details, Console URL
    instance_id = extract_clean_value(details.get("instance_id"))
    if instance_id:
        sanitized["instance_id"] = instance_id
    
    ip_address = extract_clean_value(details.get("ip_address"))
    ip_type = extract_clean_value(details.get("ip_type"))
    
    if ip_address:
        sanitized["ip_address"] = ip_address
        if ip_type:
            sanitized["ip_type"] = str(ip_type).lower()
    
    public_ip = extract_clean_value(details.get("public_ip"))
    private_ip = extract_clean_value(details.get("private_ip"))
    
    if public_ip and not ip_address:
        sanitized["ip_address"] = public_ip
        sanitized["ip_type"] = "public"
    elif private_ip and not ip_address:
        sanitized["ip_address"] = private_ip
        sanitized["ip_type"] = "private"
    
    console_url = extract_clean_value(details.get("console_url"))
    if console_url:
        sanitized["console_url"] = console_url
    
    created_at = extract_clean_value(details.get("created_at"))
    if created_at:
        sanitized["created_at"] = created_at
    else:
        sanitized["created_at"] = datetime.now(timezone.utc).isoformat()
    
    return sanitized

def normalize_resource_ids(payload: Dict[str, Any]) -> Dict[str, Any]:
    res = {}
    if not isinstance(payload, dict):
        return res
    
    # Include Instance ID, IP details, Console URL
    instance_id = extract_clean_value(payload.get("instance_id"))
    if instance_id:
        res["instance_id"] = instance_id
    
    public_ip = extract_clean_value(payload.get("public_ip"))
    private_ip = extract_clean_value(payload.get("private_ip"))
    explicit_ip = extract_clean_value(payload.get("ip_address"))
    explicit_type = extract_clean_value(payload.get("ip_type"))
    
    if explicit_ip and explicit_type:
        res["ip_address"] = explicit_ip
        res["ip_type"] = str(explicit_type).lower()
    elif public_ip:
        res["ip_address"] = public_ip
        res["ip_type"] = "public"
    elif private_ip:
        res["ip_address"] = private_ip
        res["ip_type"] = "private"
    
    console_url = extract_clean_value(payload.get("console_url"))
    if console_url:
        res["console_url"] = console_url
    
    created = extract_clean_value(payload.get("created_at"))
    if created:
        res["created_at"] = created
    else:
        res["created_at"] = datetime.now(timezone.utc).isoformat()
    
    return res

notification_cache = {}

# DEPRECATED - Use notification_handler.py instead
# This function is kept for backward compatibility but should not be used
async def unified_notification_handler(user_email: str, request_id: str, status: str, details: Dict[str, Any]):
    """DEPRECATED - Use notification_handler.py functions instead"""
    logger = logging.getLogger(__name__)
    logger.warning(f"DEPRECATED: unified_notification_handler called for {user_email}:{request_id}:{status}")
    logger.warning("Please use notification_handler.py functions instead")
    
    # Fallback to new handler
    from .notification_handler import (
        send_pr_notifications, send_deployment_notifications, 
        send_failure_notifications, send_destroy_notifications
    )
    
    try:
        if status == "pr_created":
            pr_number = details.get("pr_number", 0)
            await send_pr_notifications(user_email, request_id, pr_number)
        elif status == "deployed":
            clean_details = sanitize_deployment_details(details)
            await send_deployment_notifications(user_email, request_id, clean_details)
        elif status == "failed":
            error_msg = details.get("error_message", "Deployment failed")
            await send_failure_notifications(user_email, request_id, error_msg)
        elif status == "destroyed":
            await send_destroy_notifications(user_email, request_id)
    except Exception as e:
        logger.error(f"Error in deprecated notification handler: {e}")

def parse_terraform_outputs(outputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(outputs, dict):
        return {}
    flat = {}
    for key, val in outputs.items():
        flat[key] = extract_terraform_value(val)
    return flat

def build_minimal_deployment_payload(raw_outputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    parsed = parse_terraform_outputs(raw_outputs or {})
    normalized = normalize_resource_ids(parsed)
    minimal = {
        "instance_id": normalized.get("instance_id"),
        "ip_address": normalized.get("ip_address"),
        "ip_type": normalized.get("ip_type"),
        "console_url": normalized.get("console_url"),
        "created_at": normalized.get("created_at"),
    }
    return {k: v for k, v in minimal.items() if v is not None}

# DEPRECATED - Use notification_handler.py instead
# This function is kept for backward compatibility
async def store_bell_notification_only(user_email: str, request_id: str, status: str, title: str, message: str, details: dict):
    """DEPRECATED - Use notification_handler.store_bell_notification instead"""
    from .notification_handler import store_bell_notification
    await store_bell_notification(user_email, request_id, title, message, status, details)