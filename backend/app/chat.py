from fastapi import APIRouter, WebSocket, Query, HTTPException
from fastapi.websockets import WebSocketDisconnect
import json
import logging
from typing import Dict, Optional
import asyncio
import time
from .websocket_manager import manager
from .llm_processor import LLMProcessor
from .utils import verify_jwt_token
from .models import User
from .database import AsyncSessionLocal
from sqlalchemy.future import select
from sqlalchemy import desc

logger = logging.getLogger(__name__)
router = APIRouter()
active_processors: Dict[str, LLMProcessor] = {}

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    try:
        payload = verify_jwt_token(token)
        user_email = payload.get("sub")
        if not user_email:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # Let manager handle the WebSocket connection
    await manager.connect(websocket, user_email)

    user_info = await get_user_info(user_email, token)
    if not user_info:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "User not found. Please log in again."
        }))
        manager.disconnect(user_email)
        return

    # Check if this is a new session (no processor exists) 
    is_new_session = user_email not in active_processors
    
    # Check if this is a fresh browser session (detect browser close/refresh)
    import time
    current_time = time.time()
    last_seen = user_sessions.get(user_email, 0)
    
    # If more than 5 minutes since last connection, treat as fresh login
    is_fresh_browser_session = (current_time - last_seen) > 300  # 5 minutes
    
    # Update session timestamp
    user_sessions[user_email] = current_time
    
    # Create processor only if doesn't exist OR if fresh browser session
    try:
        if user_email not in active_processors or is_fresh_browser_session:
            active_processors[user_email] = LLMProcessor()
            active_processors[user_email].clear_user_session(user_email)
            # Clear notification tracking for fresh session
            if user_email in sent_notifications:
                sent_notifications[user_email].clear()
            is_new_session = True  # Force new session behavior
            logger.info(f"✅ Created fresh LLMProcessor for {user_email} (fresh browser session: {is_fresh_browser_session})")
        else:
            logger.info(f"✅ Reusing existing LLMProcessor for {user_email} - conversation preserved")
    except Exception as e:
        logger.error(f"❌ Failed to create LLMProcessor for {user_email}: {e}")
        # Create a minimal fallback that won't crash
        class FallbackProcessor:
            def clear_user_session(self, user_email): pass
            async def process_user_message(self, user_email, message, user_info):
                return {
                    "message": "I'm here to help with AWS infrastructure! What would you like to create?",
                    "buttons": [],
                    "show_text_input": True
                }
        active_processors[user_email] = FallbackProcessor()

    # Send connection_ready
    try:
        await websocket.send_text(json.dumps({
            "type": "connection_ready",
            "user_name": user_info.get('name', user_email.split('@')[0]),
            "timestamp": asyncio.get_event_loop().time(),
            "fresh_start": is_new_session
        }))
        logger.info(f"✅ Sent connection_ready to {user_email}")
    except Exception as e:
        logger.error(f"❌ Failed to send connection_ready to {user_email}: {e}")
        await websocket.close(code=1011, reason="Connection setup failed")
        return
    
    # Send greeting only for new sessions
    user_name = user_info.get('name', user_email.split('@')[0])
    if is_new_session:
        greeting_message = {
            "type": "chat_response",
            "message": f"Hi {user_name}! I'm here to help you create AWS resources. What would you like to build today?",
            "buttons": [],
            "show_text_input": True,
            "timestamp": asyncio.get_event_loop().time(),
            "greeting": True,
            "fresh_start": True
        }
        
        try:
            await websocket.send_text(json.dumps(greeting_message))
            logger.info(f"✅ Sent greeting to new session: {user_email}")
        except Exception as e:
            logger.error(f"❌ Failed to send greeting to {user_email}: {e}")
            await websocket.close(code=1011, reason="Greeting failed")
            return
    else:
        logger.info(f"✅ Reconnected to existing session: {user_email} - no greeting sent")
    
    # Send pending notifications only for new sessions to avoid duplicates
    if is_new_session:
        await send_pending_notifications(user_email, user_info)
    else:
        logger.info(f"Skipping notifications for existing session: {user_email}")

    llm_processor = active_processors[user_email]

    try:
        while True:
            data = await websocket.receive_text()
            print(f"🔥 WEBSOCKET RECEIVED: {user_email} -> {data[:100]}")
            logger.info(f"Received WebSocket message from {user_email}: {data[:200]}...")
            
            message_data = json.loads(data)
            message_type = message_data.get("type")
            print(f"🔥 MESSAGE TYPE: {message_type}")
            logger.info(f"Message type: {message_type}")

            if message_type == "chat_message":
                print(f"🔥 CHAT MESSAGE RECEIVED: {user_email} -> {message_data.get('message', '')[:50]}")
                logger.info(f"Processing chat message for {user_email}")
                await handle_chat_message(user_email, message_data, llm_processor, token)
                print(f"🔥 CHAT MESSAGE PROCESSED: {user_email}")
            elif message_type == "clear_conversation":
                logger.info(f"Clearing conversation for {user_email}")
                await handle_clear_conversation(user_email, llm_processor, token)
            elif message_type == "ping":
                await handle_ping(user_email, message_data)
            elif message_type == "popup_delivered":
                await handle_popup_delivered(user_email, message_data)
            else:
                print(f"🔥 UNKNOWN MESSAGE TYPE: {message_type} from {user_email}")
                logger.warning(f"Unknown message type: {message_type} from {user_email}")
                await manager.send_personal_message(user_email, {
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for {user_email}")
        manager.disconnect(user_email)
        # Update last seen time for session tracking
        user_sessions[user_email] = time.time()
    except json.JSONDecodeError as e:
        print(f"🔥 JSON ERROR: {user_email} -> {e}")
        logger.error(f"❌ JSON decode error for {user_email}: {e}")
        await handle_json_error(user_email)
    except Exception as e:
        logger.exception(f"❌ WebSocket error for user {user_email}: {e}")
        try:
            await manager.send_personal_message(user_email, {
                "type": "error",
                "message": "Connection error occurred. Please refresh the page."
            })
        except:
            pass
        manager.disconnect(user_email)

async def handle_chat_message(user_email: str, message_data: dict, llm_processor: LLMProcessor, token: str):
    print(f"🔥 HANDLE_CHAT_MESSAGE CALLED: {user_email} -> {message_data.get('message', '')[:50]}")
    try:
        user_info = await get_user_info(user_email, token)
        if not user_info:
            await manager.send_personal_message(user_email, {
                "type": "chat_response",
                "message": "User not found. Please log in again.",
                "buttons": [],
                "show_text_input": True
            })
            return

        msg_content = message_data["message"]
        print(f"🔥 PROCESSING MESSAGE: {user_email} -> '{msg_content}'")
        logger.info(f"💬 Processing chat message from {user_email}: '{msg_content}'")
        
        # Use enhanced LLM processor for natural conversation with timeout
        try:
            logger.info(f"💬 Processing message from {user_email}: '{msg_content[:50]}...'")
            response = await asyncio.wait_for(
                llm_processor.process_user_message(user_email, msg_content, user_info),
                timeout=12.0
            )
            logger.info(f"✅ Response generated for {user_email}: '{response.get('message', '')[:50]}...'")
        except Exception as e:
            print(f"🔥 LLM ERROR: {user_email} -> {e}")
            logger.error(f"❌ LLM processing failed for {user_email}: {e}")
            import traceback
            print(f"🔥 TRACEBACK: {traceback.format_exc()}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            # Safe fallback response that handles the specific message
            if "ubuntu" in msg_content.lower() and "t3.micro" in msg_content.lower() and "dev" in msg_content.lower():
                response = {
                    "message": f"Perfect! I've got t3.micro Ubuntu in DEV environment. Ready to configure networking and deploy?",
                    "buttons": [],
                    "show_text_input": True
                }
            elif "ubuntu" in msg_content.lower():
                response = {
                    "message": f"Great! I see you want Ubuntu. What instance type and environment would you like?",
                    "buttons": [],
                    "show_text_input": True
                }
            else:
                response = {
                    "message": f"Hi {user_info.get('name', 'there')}! I'm your AWS infrastructure assistant. What would you like to create today?",
                    "buttons": [],
                    "show_text_input": True
                }
        
        logger.info(f"📤 Sending response to {user_email}: {response.get('message', '')[:100]}...")

        response_message = {
            "type": "chat_response",
            "message": response["message"],
            "buttons": response.get("buttons", []),
            "show_text_input": response.get("show_text_input", True),
            "timestamp": message_data.get("timestamp")
        }
        
        print(f"🔥 SENDING RESPONSE: {user_email} -> {response_message.get('message', '')[:50]}")
        logger.info(f"📤 Sending response message: {response_message}")
        await manager.send_personal_message(user_email, response_message)
        print(f"🔥 RESPONSE SENT: {user_email}")
        logger.info(f"✅ Response sent successfully to {user_email}")
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout processing message for {user_email}")
        try:
            # Extract basic parameters for quick response
            if "ubuntu" in msg_content.lower() and "t3.micro" in msg_content.lower():
                await manager.send_personal_message(user_email, {
                    "type": "chat_response",
                    "message": "Perfect! I see you want t3.micro with Ubuntu. Let me help you configure this EC2 instance. What environment would you like - DEV, QA, or PROD?",
                    "buttons": [],
                    "show_text_input": True
                })
            else:
                await manager.send_personal_message(user_email, {
                    "type": "chat_response",
                    "message": "I'm ready to help! Please tell me what AWS resources you'd like to create.",
                    "buttons": [],
                    "show_text_input": True
                })
        except Exception as e2:
            logger.error(f"❌ Failed to send timeout message: {e2}")
    except Exception as e:
        print(f"🔥 HANDLE_CHAT_MESSAGE ERROR: {user_email} -> {e}")
        logger.error(f"❌ Error handling chat message for {user_email}: {e}")
        import traceback
        print(f"🔥 HANDLE_CHAT_MESSAGE TRACEBACK: {traceback.format_exc()}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        try:
            await manager.send_personal_message(user_email, {
                "type": "chat_response",
                "message": "I'm here to help with AWS infrastructure! What would you like to create?",
                "buttons": [],
                "show_text_input": True
            })
        except Exception as e2:
            logger.error(f"❌ Failed to send error message to {user_email}: {e2}")

async def handle_clear_conversation(user_email: str, llm_processor: LLMProcessor, token: str):
    try:
        # Clear the user session completely
        llm_processor.clear_user_session(user_email)
        
        user_info = await get_user_info(user_email, token)
        user_name = user_info.get('name', user_email.split('@')[0]) if user_info else 'there'
        
        await manager.send_personal_message(user_email, {
            "type": "chat_response",
            "message": f"Conversation cleared! Hi {user_name}, what would you like to create?",
            "buttons": [],
            "show_text_input": True,
            "fresh_start": True
        })
    except Exception:
        await manager.send_personal_message(user_email, {
            "type": "error",
            "message": "Failed to clear conversation."
        })

async def handle_ping(user_email: str, message_data: dict):
    try:
        await manager.send_personal_message(user_email, {
            "type": "pong",
            "timestamp": message_data.get("timestamp")
        })
    except Exception as e:
        logger.error(f"Error handling ping for {user_email}: {e}")

async def handle_popup_delivered(user_email: str, message_data: dict):
    try:
        popup_id = message_data.get("popup_id")
        timestamp = message_data.get("timestamp")
        logger.info(f"✅ POPUP DELIVERED to {user_email}: {popup_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Error handling popup delivery confirmation for {user_email}: {e}")

async def handle_json_error(user_email: str):
    try:
        await manager.send_personal_message(user_email, {
            "type": "error",
            "message": "Invalid message format. Please try again."
        })
        logger.error(f"❌ JSON error handled for {user_email}")
    except Exception as e:
        logger.error(f"❌ Failed to handle JSON error for {user_email}: {e}")

# Track sent notifications to avoid duplicates
sent_notifications: Dict[str, set] = {}

# Track user sessions to detect fresh logins
user_sessions: Dict[str, float] = {}

async def send_pending_notifications(user_email: str, user_info: dict):
    """Send only NEW unread notifications to user when they connect"""
    try:
        # Initialize sent notifications tracking for user
        if user_email not in sent_notifications:
            sent_notifications[user_email] = set()
        
        async with AsyncSessionLocal() as db:
            from .models import UserNotification
            from datetime import datetime, timedelta
            
            # Only get notifications from last 1 hour to avoid old notifications
            recent_time = datetime.now() - timedelta(hours=1)
            
            result = await db.execute(
                select(UserNotification)
                .where(
                    UserNotification.user_id == user_info['user_id'],
                    UserNotification.is_read.is_(False),
                    UserNotification.created_at > recent_time
                )
                .order_by(desc(UserNotification.created_at))
                .limit(5)  # Only latest 5 notifications
            )
            notifications = result.scalars().all()
            
            new_notifications = 0
            for notif in notifications:
                notif_id = str(notif.id)
                
                # Skip if already sent to this user
                if notif_id in sent_notifications[user_email]:
                    continue
                
                # Send as bell notification only
                await manager.send_bell_notification(
                    user_email,
                    notif.title,
                    notif.message,
                    notif.status or "info",
                    notif.deployment_details or {},
                    notif_id
                )
                
                # Mark as sent
                sent_notifications[user_email].add(notif_id)
                new_notifications += 1
            
            logger.info(f"Sent {new_notifications} NEW notifications to {user_email}")
            
    except Exception as e:
        logger.error(f"Error sending pending notifications to {user_email}: {e}")

async def get_user_info(user_email: str, jwt_token: str = None) -> Optional[dict]:
    try:
        async with AsyncSessionLocal() as db:
            from .models import EnvironmentApproval
            from datetime import datetime
            
            # Get user data
            result = await db.execute(select(User).where(User.email == user_email))
            user = result.scalar_one_or_none()
            if not user:
                return None
            
            # Get environment approvals with expiry data
            approvals_result = await db.execute(
                select(EnvironmentApproval)
                .where(EnvironmentApproval.user_id == user.id)
                .where(EnvironmentApproval.status == "approved")
            )
            approvals = approvals_result.scalars().all()
            
            # Build environment access and expiry dictionaries
            environment_access = user.environment_access or {}
            environment_expiry = {}
            
            # Add expiry data from approvals and update database if expired
            db_needs_update = False
            for approval in approvals:
                if approval.expires_at:
                    environment_expiry[approval.environment] = approval.expires_at.isoformat()
                    # Check if expired and update access accordingly
                    if approval.expires_at < datetime.utcnow():
                        if environment_access.get(approval.environment, True):  # Only update if currently True
                            environment_access[approval.environment] = False
                            db_needs_update = True
                    else:
                        environment_access[approval.environment] = True
            
            # Update database if any environment access changed due to expiry
            if db_needs_update:
                user.environment_access = environment_access
                await db.commit()
                logger.info(f"Updated expired environment access for {user_email}: {environment_access}")
            
            return {
                "user_id": str(user.id),
                "name": user.name,
                "email": user.email,
                "department": user.department,
                "manager_email": user.manager_email,
                "environment_access": environment_access,
                "environment_expiry": environment_expiry,
                "jwt_token": jwt_token
            }
    except Exception as e:
        logger.error(f"Error fetching user info for {user_email}: {e}")
        return None

@router.get("/chat/health")
async def chat_health():
    try:
        connected_users = manager.get_connected_users()
        return {
            "status": "healthy",
            "service": "chat",
            "connected_users": len(connected_users),
            "active_processors": len(active_processors),
            "connected_user_emails": connected_users
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "chat",
            "error": str(e)
        }

@router.post("/chat/cleanup")
async def cleanup_inactive_processors():
    try:
        connected_users = manager.get_connected_users()
        connected_emails = set(connected_users)
        inactive_emails = [email for email in active_processors.keys() if email not in connected_emails]
        cleaned_count = 0
        for email in inactive_emails:
            try:
                del active_processors[email]
                cleaned_count += 1
            except KeyError:
                continue
        return {
            "cleaned_up": cleaned_count,
            "active_processors": len(active_processors),
            "connected_users": len(connected_emails)
        }
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@router.get("/chat/connections")
async def get_connections():
    try:
        connected_users = manager.get_connected_users()
        return {
            "total_connections": len(connected_users),
            "connected_users": connected_users
        }
    except Exception as e:
        logger.error(f"Failed to get connections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connections: {str(e)}")

@router.post("/chat/test")
async def test_chat_message(request: dict):
    try:
        message = request.get("message")
        if not message:
            return {
                "status": "error",
                "message": "Message required",
                "response": {"message": "Please provide a message", "show_text_input": True}
            }
        
        # Mock user info for testing
        mock_user_info = {
            "user_id": "test123",
            "name": "Test User",
            "email": "test@company.com",
            "department": "devops",
            "environment_access": {"dev": True, "qa": False, "prod": False}
        }
        
        # Simple fallback responses for testing
        message_lower = message.lower()
        
        if "cost" in message_lower:
            if "t3.micro" in message_lower:
                response = {
                    "message": "💰 Estimated cost for t3.micro: Instance $8.50/month + Storage $2.00/month = $10.50/month",
                    "buttons": [],
                    "show_text_input": True
                }
            else:
                response = {
                    "message": "💰 I can estimate costs for EC2 instances. Please specify instance type.",
                    "buttons": [],
                    "show_text_input": True
                }
        elif "s3" in message_lower and any(w in message_lower for w in ["what", "tell", "explain"]):
            response = {
                "message": "**Amazon S3** is object storage for files, backups, and static websites. Need help creating an EC2 instance?",
                "buttons": [{"text": "Yes, Create EC2", "value": "yes"}],
                "show_text_input": True
            }
        elif "lunch" in message_lower:
            response = {
                "message": "Enjoy your lunch! 🍽️ I'll be here when you get back to help with your AWS infrastructure needs.",
                "buttons": [],
                "show_text_input": True
            }
        elif any(w in message_lower for w in ["create", "deploy", "instance"]):
            response = {
                "message": "Great! I'd love to help you create an EC2 instance. What are your requirements?",
                "buttons": [],
                "show_text_input": True
            }
        else:
            response = {
                "message": "I'm here to help you create AWS EC2 instances! What would you like to build today?",
                "buttons": [],
                "show_text_input": True
            }
        
        return {
            "status": "success",
            "user_email": "test@company.com",
            "message": message,
            "response": response
        }
    except Exception as e:
        logger.error(f"Test chat error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "response": {"message": "Error processing message", "show_text_input": True}
        }