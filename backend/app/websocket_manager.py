# websocket_manager.py - FIXED VERSION
from fastapi import WebSocket
from typing import Dict, Optional
import json
import logging
import asyncio

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Store user mapping and accept connection"""
        try:
            await websocket.accept()
            self.active_connections[user_id] = websocket
            logger.info(f"✅ User {user_id} connected via WebSocket. Total connections: {len(self.active_connections)}")
        except Exception as e:
            logger.error(f"❌ Failed to connect user {user_id}: {e}")

    def disconnect(self, user_id: str):
        """Remove user connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"User {user_id} disconnected from WebSocket. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, user_id: str, message: dict):
        """Send message to specific user"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                message_json = json.dumps(message)
                await websocket.send_text(message_json)
                logger.info(f"✅ Sent {message.get('type', 'unknown')} to {user_id}")
                logger.debug(f"Message content: {message_json}")
            except Exception as e:
                logger.error(f"❌ Error sending message to {user_id}: {e}")
                self.disconnect(user_id)
        else:
            logger.warning(f"⚠️ User {user_id} not connected - message not sent: {message.get('type', 'unknown')}")

    async def send_popup_notification(
        self, 
        user_id: str, 
        title: str, 
        message: str, 
        notification_type: str = "info"
    ):
        """Send ONLY popup notification (temporary, simple message)"""
        import time
        current_timestamp = time.time()
        
        notification_data = {
            "type": "popup_notification",
            "popup": {
                "id": f"{user_id}_{title}_{int(current_timestamp)}",
                "title": title,
                "message": message,
                "type": notification_type,
                "duration": 18000,  # 18 seconds for all popups
                "timestamp": current_timestamp
            }
        }
        
        logger.info(f"🚨 POPUP SENDING: {title} -> {user_id}")
        logger.info(f"🚨 POPUP DATA: {notification_data}")
        
        if user_id in self.active_connections:
            await self.send_personal_message(user_id, notification_data)
            logger.info(f"✅ POPUP SENT SUCCESSFULLY: {title} -> {user_id}")
        else:
            logger.warning(f"❌ USER NOT CONNECTED: {user_id} - popup not sent")
        
        # Ensure popup delivery
        import asyncio
        await asyncio.sleep(0.1)

    async def send_bell_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        notification_type: str = "info",
        extra_data: Optional[dict] = None,
        request_id: str = None
    ):
        """Send bell notification (WebSocket only, database handled by unified_notification_handler)"""
        import time
        current_timestamp = time.time()
        
        # Send via WebSocket only
        bell_notification = {
            "type": "notification",
            "message": message,
            "title": title,
            "notification_type": notification_type,
            "timestamp": current_timestamp,
            "data": extra_data or {}
        }
        
        logger.info(f"🔔 BELL NOTIFICATION (to bell icon): {title} -> {user_id}")
        await self.send_personal_message(user_id, bell_notification)

    async def send_deployment_notification(
        self,
        user_id: str,
        request_id: str,
        deployment_details: dict
    ):
        """Send deployment success popup and bell notification"""
        try:
            # Check if already sent to prevent duplicates
            notification_key = f"deployment_{request_id}_{user_id}"
            if hasattr(self, '_sent_notifications'):
                if notification_key in self._sent_notifications:
                    logger.info(f"Duplicate deployment notification prevented for {request_id}")
                    return
            else:
                self._sent_notifications = set()
            
            self._sent_notifications.add(notification_key)
            
            instance_id = deployment_details.get('instance_id', '')
            ip_address = deployment_details.get('ip_address', '')
            console_url = deployment_details.get('console_url', '')
            short_id = request_id.split('_')[-1]
            
            # Enhanced deployment SUCCESS popup with more details
            if instance_id and ip_address:
                popup_message = f"🚀 Deployment Complete!\n\nInstance: {instance_id}\nIP: {ip_address}\nStatus: Running"
            elif instance_id:
                popup_message = f"🚀 Deployment Complete!\n\nInstance: {instance_id}\nStatus: Ready"
            else:
                popup_message = f"🚀 Deployment Complete!\n\nInfrastructure: {short_id}\nStatus: Ready"
            
            await self.send_popup_notification(
                user_id,
                "🎉 Infrastructure Deployed",
                popup_message,
                "success"
            )
            
            # Enhanced bell notification with actionable details
            bell_message = f"Your infrastructure {short_id} has been deployed successfully!"
            if instance_id:
                bell_message += f"\n\n📋 Instance ID: {instance_id}"
            if ip_address:
                bell_message += f"\n🌐 IP Address: {ip_address}"
            if console_url:
                bell_message += f"\n🔗 AWS Console: Available"
            bell_message += f"\n\n✅ Status: Ready for use"
            
            await self.send_bell_notification(
                user_id,
                f"🚀 Infrastructure Ready - {short_id}",
                bell_message,
                "success",
                deployment_details,
                request_id
            )
            
            logger.info(f"✅ Sent deployment success notification for {request_id}")
            
        except Exception as e:
            logger.error(f"Error sending deployment notification: {e}")
    
    async def send_deployment_failure_notification(
        self,
        user_id: str,
        request_id: str,
        error_message: str
    ):
        """Send deployment failure popup and bell notification"""
        try:
            # Check if already sent to prevent duplicates
            notification_key = f"failure_{request_id}_{user_id}"
            if hasattr(self, '_sent_notifications'):
                if notification_key in self._sent_notifications:
                    logger.info(f"Duplicate failure notification prevented for {request_id}")
                    return
            else:
                self._sent_notifications = set()
            
            self._sent_notifications.add(notification_key)
            
            short_id = request_id.split('_')[-1]
            
            # Enhanced failure popup with more context
            popup_message = f"❌ Deployment Failed\n\nInfrastructure: {short_id}\nReason: {error_message[:50]}..."
            
            await self.send_popup_notification(
                user_id,
                "⚠️ Deployment Failed",
                popup_message,
                "error"
            )
            
            # Enhanced bell notification with troubleshooting info
            bell_message = f"Deployment of infrastructure {short_id} failed.\n\n❌ Error: {error_message}\n\n💡 Next steps:\n• Check configuration parameters\n• Verify AWS permissions\n• Contact support if issue persists"
            
            await self.send_bell_notification(
                user_id,
                f"❌ Deployment Failed - {short_id}",
                bell_message,
                "error",
                {"error_message": error_message, "request_id": request_id}
            )
            
            logger.info(f"✅ Sent deployment failure notification for {request_id}")
            
        except Exception as e:
            logger.error(f"Error sending failure notification: {e}")

    async def send_pr_notification(self, user_id: str, request_id: str, pr_number: int):
        """Send PR created popup and bell notification"""
        try:
            # Check if already sent to prevent duplicates
            notification_key = f"pr_{request_id}_{pr_number}_{user_id}"
            if hasattr(self, '_sent_notifications'):
                if notification_key in self._sent_notifications:
                    logger.info(f"Duplicate PR notification prevented for {request_id}")
                    return
            else:
                self._sent_notifications = set()
            
            self._sent_notifications.add(notification_key)
            
            short_id = request_id.split('_')[-1]
            
            # Enhanced PR popup with more details
            popup_msg = f"📋 Request Submitted\n\nPR #{pr_number} created\nStatus: Awaiting approval"
            
            await self.send_popup_notification(
                user_id,
                "🔄 Request Submitted",
                popup_msg,
                "info"
            )
            
            # Enhanced bell notification with timeline info
            bell_msg = f"Your infrastructure request {short_id} has been submitted for approval.\n\n📋 Pull Request: #{pr_number}\n👥 Status: Awaiting DevOps review\n⏱️ Typical approval time: 15-30 minutes\n\nYou'll be notified when deployment begins."
            
            await self.send_bell_notification(
                user_id,
                f"📋 Request Submitted - {short_id}",
                bell_msg,
                "info",
                {"pr_number": pr_number, "request_id": request_id}
            )
            
            logger.info(f"✅ Sent PR notification for {request_id} - PR #{pr_number}")
            
        except Exception as e:
            logger.error(f"Error sending PR notification: {e}")

    async def send_approval_notification(self, user_id: str, environment: str, approved: bool):
        """Send environment approval popup and bell notification"""
        if approved:
            # APPROVAL popup - specific message
            popup_msg = f"✅ Access Approved! You can now use {environment.upper()} environment"
            
            await self.send_popup_notification(
                user_id,
                "Environment Access Approved",
                popup_msg,
                "success"
            )
            
            # Bell notification with approval details
            bell_msg = f"Your manager has approved access to the {environment.upper()} environment. You can now create and deploy resources there. Access expires in 48 hours."
            
            await self.send_bell_notification(
                user_id,
                f"{environment.upper()} Access Approved",
                bell_msg,
                "success",
                {"environment": environment, "expires_in_hours": 48}
            )
        else:
            # DENIAL popup - specific message
            popup_msg = f"❌ Access Denied! {environment.upper()} environment request rejected"
            
            await self.send_popup_notification(
                user_id,
                "Environment Access Denied",
                popup_msg,
                "error"
            )
            
            # Bell notification with denial details
            bell_msg = f"Your request for {environment.upper()} environment access has been denied by your manager. Please contact them for clarification."
            
            await self.send_bell_notification(
                user_id,
                f"{environment.upper()} Access Denied",
                bell_msg,
                "error",
                {"environment": environment}
            )

    async def send_error_notification(self, user_id: str, title: str, message: str, request_id: str = None):
        """Send error notification to user"""
        # Send popup (temporary)
        await self.send_popup_notification(
            user_id,
            title,
            message,
            "error"
        )
        
        # Send bell notification (persistent) for deployment failures
        if request_id:
            short_id = request_id.split('_')[-1] if request_id else "unknown"
            await self.send_bell_notification(
                user_id,
                f"Deployment Failed - {short_id}",
                f"{title}: {message}",
                "error",
                {"request_id": request_id}
            )

    async def broadcast_message(self, message: dict):
        """Send message to all connected users (admin only)"""
        disconnected_users = []
        
        for user_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                disconnected_users.append(user_id)
        
        for user_id in disconnected_users:
            self.disconnect(user_id)
        
        logger.info(f"Broadcasted message to {len(self.active_connections)} users")

    def get_connected_users(self) -> list:
        """Get list of currently connected users"""
        connected = list(self.active_connections.keys())
        logger.info(f"🔗 Currently connected users: {connected}")
        return connected

    def is_user_connected(self, user_id: str) -> bool:
        """Check if specific user is connected"""
        return user_id in self.active_connections

    async def send_new_notification_only(self, user_id: str, notification_data: dict):
        """Send only new notification without past notifications"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(json.dumps({
                    "type": "new_notification",
                    "notification": notification_data
                }))
                logger.info(f"📨 Sent new notification to {user_id}: {notification_data.get('title', 'Unknown')}")
            except Exception as e:
                logger.error(f"❌ Error sending new notification to {user_id}: {e}")
                self.disconnect(user_id)
        else:
            logger.warning(f"⚠️ User {user_id} not connected - new notification not sent")


manager = ConnectionManager()