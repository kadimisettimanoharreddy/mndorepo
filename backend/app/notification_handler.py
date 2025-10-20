"""
Separate notification handler to properly manage popup vs bell notifications
"""
import logging
import time
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from .websocket_manager import manager
from .models import User, InfrastructureRequest, UserNotification
from .database import AsyncSessionLocal
from sqlalchemy.future import select
import uuid

logger = logging.getLogger(__name__)

# Cache to prevent duplicate notifications
notification_cache = {}

async def send_popup_only(user_email: str, title: str, message: str, notification_type: str = "info"):
    """Send ONLY popup notification (temporary snackbar) - NO database storage"""
    if manager.is_user_connected(user_email):
        await manager.send_popup_notification(user_email, title, message, notification_type)
        logger.info(f"📱 POPUP SENT: {title} -> {user_email}")
    else:
        logger.info(f"⚠️ User {user_email} offline - popup skipped")

# Removed - using direct database storage instead

async def send_approval_notifications(user_email: str, environment: str, approved: bool):
    """Send approval/denial notifications - WebSocket popup + Database storage"""
    if approved:
        # WebSocket → Popup (temporary)
        await send_popup_only(
            user_email,
            "Environment Access Approved",
            f"✅ Access to {environment.upper()} environment approved!",
            "success"
        )
        
        # Database → Bell notification (persistent)
        await store_bell_notification(
            user_email,
            f"env_approval_{environment}_{int(time.time())}",
            f"Environment Access Approved - {environment.upper()}",
            f"Your manager has approved access to the {environment.upper()} environment. You can now create and deploy resources there. Access expires in 48 hours.",
            "success",
            {"environment": environment, "expires_in_hours": 48}
        )
    else:
        # WebSocket → Popup (temporary)
        await send_popup_only(
            user_email,
            "Environment Access Denied",
            f"❌ Access to {environment.upper()} environment denied",
            "error"
        )
        
        # Database → Bell notification (persistent)
        await store_bell_notification(
            user_email,
            f"env_denial_{environment}_{int(time.time())}",
            f"Environment Access Denied - {environment.upper()}",
            f"Your request for {environment.upper()} environment access has been denied by your manager. Please contact them for clarification.",
            "error",
            {"environment": environment}
        )

async def send_pr_notifications(user_email: str, request_id: str, pr_number: int, service_type: str = "EC2"):
    """Send PR created notifications - WebSocket popup + Database storage"""
    short_id = request_id.split('_')[-1]
    
    # Log what data we received
    logger.info(f"📋 PR NOTIFICATION DATA for {request_id}:")
    logger.info(f"   User: {user_email}")
    logger.info(f"   PR Number: {pr_number}")
    logger.info(f"   Service Type: {service_type}")
    
    # Service-specific messaging with better user understanding
    if service_type.lower() == "s3":
        popup_msg = f"🪣 S3 Bucket Request Submitted - {short_id}"
        bell_message = f"Your S3 bucket request '{short_id}' is now under review.\n\n📋 Pull Request: #{pr_number}\n👥 Status: Awaiting DevOps approval\n⏱️ Typical review time: 15-30 minutes\n\n🚀 What happens next:\n1. DevOps reviews your S3 bucket configuration\n2. PR gets approved and automatically merged\n3. S3 bucket creation starts immediately\n4. You'll get notified when your bucket is ready to use\n\n💡 This follows our approval-first deployment process for security."
    elif service_type.lower() == "lambda":
        popup_msg = f"⚡ Lambda Function Request Submitted - {short_id}"
        bell_message = f"Your Lambda function request '{short_id}' is now under review.\n\n📋 Pull Request: #{pr_number}\n👥 Status: Awaiting DevOps approval\n⏱️ Typical review time: 15-30 minutes\n\n🚀 What happens next:\n1. DevOps reviews your Lambda function configuration\n2. PR gets approved and automatically merged\n3. Lambda function deployment starts immediately\n4. You'll get notified when your function is ready to invoke\n\n💡 This follows our approval-first deployment process for security."
    else:  # EC2 or default
        popup_msg = f"🖥️ EC2 Instance Request Submitted - {short_id}"
        bell_message = f"Your EC2 instance request '{short_id}' is now under review.\n\n📋 Pull Request: #{pr_number}\n👥 Status: Awaiting DevOps approval\n⏱️ Typical review time: 15-30 minutes\n\n🚀 What happens next:\n1. DevOps reviews your EC2 instance configuration\n2. PR gets approved and automatically merged\n3. EC2 instance deployment starts immediately\n4. You'll get notified when your instance is ready to use\n\n💡 This follows our approval-first deployment process for security."
    
    logger.info(f"📨 POPUP MESSAGE: {popup_msg}")
    await send_popup_only(
        user_email,
        "PR Created - Awaiting Approval",
        popup_msg,
        "info"
    )
    
    logger.info(f"🔔 BELL MESSAGE: {bell_message[:100]}...")
    await store_bell_notification(
        user_email,
        request_id,
        f"{service_type} PR Created - {short_id}",
        bell_message,
        "info",
        {"request_id": request_id, "pr_number": pr_number, "service_type": service_type.lower(), "stage": "pr_created"}
    )

async def send_deployment_notifications(user_email: str, request_id: str, deployment_details: Dict[str, Any]):
    """Send deployment success notifications - WebSocket popup + Database storage for EC2, S3, Lambda"""
    short_id = request_id.split('_')[-1]
    service_type = request_id.split('_')[0].lower()
    
    # Log what data we received
    logger.info(f"📊 DEPLOYMENT NOTIFICATION DATA for {request_id}:")
    logger.info(f"   User: {user_email}")
    logger.info(f"   Service: {service_type}")
    logger.info(f"   Details: {deployment_details}")
    
    # Override service_type from deployment_details if available
    if deployment_details.get('service_type'):
        service_type = deployment_details.get('service_type')
    
    # Service-specific notification handling
    if service_type == 'ec2':
        # EC2 Instance notifications
        instance_id = deployment_details.get('instance_id', '')
        ip_address = deployment_details.get('ip_address', '')
        ip_type = deployment_details.get('ip_type', 'IP')
        console_url = deployment_details.get('console_url', '')
        
        if instance_id and ip_address:
            popup_msg = f"🚀 EC2 Instance {short_id} is ready!\nInstance: {instance_id}\nIP: {ip_address}"
        elif instance_id:
            popup_msg = f"🚀 EC2 Instance {short_id} is ready!\nInstance: {instance_id}"
        else:
            popup_msg = f"🚀 EC2 Instance {short_id} deployed successfully!"
        
        bell_parts = [f"Your EC2 instance {short_id} has been deployed successfully!"]
        if instance_id:
            bell_parts.append(f"\n📋 Instance ID: {instance_id}")
        if ip_address:
            bell_parts.append(f"🌐 {ip_type.title()} IP: {ip_address}")
        if console_url:
            bell_parts.append(f"🔗 AWS Console: Available")
        bell_parts.append(f"\n✅ Status: Ready for use")
        bell_parts.append(f"🔑 SSH Access: Use your keypair to connect")
        
    elif service_type == 's3' or deployment_details.get('service_type') == 's3':
        # S3 Bucket notifications
        bucket_name = deployment_details.get('bucket_name', '')
        bucket_arn = deployment_details.get('bucket_arn', '')
        region = deployment_details.get('region', '')
        console_url = deployment_details.get('console_url', '')
        bucket_domain = deployment_details.get('bucket_domain', '')
        
        if bucket_name and region:
            popup_msg = f"🪣 S3 Bucket {short_id} is ready!\nBucket: {bucket_name}\nRegion: {region}"
        elif bucket_name:
            popup_msg = f"🪣 S3 Bucket {short_id} is ready!\nBucket: {bucket_name}"
        else:
            popup_msg = f"🪣 S3 Bucket {short_id} deployed successfully!"
        
        bell_parts = [f"Your S3 bucket {short_id} has been created successfully!"]
        if bucket_name:
            bell_parts.append(f"\n🪣 Bucket Name: {bucket_name}")
        if bucket_arn:
            bell_parts.append(f"🔗 Bucket ARN: {bucket_arn}")
        if region:
            bell_parts.append(f"🌍 Region: {region}")
        if bucket_domain:
            bell_parts.append(f"🌐 Domain: {bucket_domain}")
        if console_url:
            bell_parts.append(f"🔗 AWS Console: Available")
        bell_parts.append(f"\n✅ Status: Ready for use")
        bell_parts.append(f"📁 Upload files: aws s3 cp file.txt s3://{bucket_name}/")
        bell_parts.append(f"📋 List contents: aws s3 ls s3://{bucket_name}/")
        
    elif service_type == 'lambda' or deployment_details.get('service_type') == 'lambda':
        # Lambda Function notifications
        function_name = deployment_details.get('function_name', '')
        function_arn = deployment_details.get('function_arn', '')
        function_url = deployment_details.get('function_url', '')
        runtime = deployment_details.get('runtime', '')
        console_url = deployment_details.get('console_url', '')
        
        if function_name and runtime:
            popup_msg = f"⚡ Lambda Function {short_id} is ready!\nFunction: {function_name}\nRuntime: {runtime}"
        elif function_name:
            popup_msg = f"⚡ Lambda Function {short_id} is ready!\nFunction: {function_name}"
        else:
            popup_msg = f"⚡ Lambda Function {short_id} deployed successfully!"
        
        bell_parts = [f"Your Lambda function {short_id} has been deployed successfully!"]
        if function_name:
            bell_parts.append(f"\n⚡ Function Name: {function_name}")
        if function_arn:
            bell_parts.append(f"🔗 Function ARN: {function_arn}")
        if runtime:
            bell_parts.append(f"🔧 Runtime: {runtime}")
        if function_url:
            bell_parts.append(f"🌐 Function URL: {function_url}")
        if console_url:
            bell_parts.append(f"🔗 AWS Console: Available")
        bell_parts.append(f"\n✅ Status: Ready for use")
        bell_parts.append(f"🚀 Invoke: aws lambda invoke --function-name {function_name} response.json")
        bell_parts.append(f"📋 Test: Use AWS Console or CLI to test function")
        
    else:
        # Generic fallback
        popup_msg = f"🚀 Infrastructure {short_id} deployed successfully!"
        bell_parts = [f"Your infrastructure {short_id} has been deployed successfully!"]
    
    bell_message = "\n".join(bell_parts)
    
    logger.info(f"📨 POPUP MESSAGE: {popup_msg}")
    await send_popup_only(
        user_email,
        f"{service_type.upper()} Ready!",
        popup_msg,
        "success"
    )
    
    # Ensure console_url is included in deployment_details for frontend button
    enhanced_details = dict(deployment_details)
    enhanced_details['service_type'] = service_type
    if deployment_details.get('console_url'):
        enhanced_details['has_console_url'] = True
    
    logger.info(f"🔔 BELL MESSAGE: {bell_message[:100]}...")
    await store_bell_notification(user_email, request_id, f"{service_type.upper()} Ready - {short_id}", bell_message, "success", enhanced_details)

async def send_failure_notifications(user_email: str, request_id: str, error_message: str, service_type: str = "EC2"):
    """Send deployment failure notifications - WebSocket popup + Database storage"""
    short_id = request_id.split('_')[-1]
    
    # Log what data we received
    logger.info(f"❌ FAILURE NOTIFICATION DATA for {request_id}:")
    logger.info(f"   User: {user_email}")
    logger.info(f"   Service Type: {service_type}")
    logger.info(f"   Error: {error_message[:100]}...")
    
    # Parse common errors into user-friendly messages
    user_friendly_message = parse_terraform_error(error_message)
    logger.info(f"   Parsed: {user_friendly_message}")
    
    # Service-specific failure messaging
    if service_type.lower() == "s3":
        popup_msg = f"🪣 S3 bucket {short_id} failed: {user_friendly_message[:50]}{'...' if len(user_friendly_message) > 50 else ''}"
        bell_message = f"S3 bucket deployment {short_id} failed.\n\n❌ Issue: {user_friendly_message}\n\n💡 Next Steps:\n• Check bucket name availability\n• Verify AWS S3 permissions\n• Ensure bucket name follows S3 naming rules\n• Try again or contact support"
    elif service_type.lower() == "lambda":
        popup_msg = f"⚡ Lambda function {short_id} failed: {user_friendly_message[:50]}{'...' if len(user_friendly_message) > 50 else ''}"
        bell_message = f"Lambda function deployment {short_id} failed.\n\n❌ Issue: {user_friendly_message}\n\n💡 Next Steps:\n• Check function name availability\n• Verify AWS Lambda permissions\n• Ensure runtime is supported\n• Try again or contact support"
    else:  # EC2 or default
        popup_msg = f"🖥️ EC2 instance {short_id} failed: {user_friendly_message[:50]}{'...' if len(user_friendly_message) > 50 else ''}"
        bell_message = f"EC2 instance deployment {short_id} failed.\n\n❌ Issue: {user_friendly_message}\n\n💡 Next Steps:\n• Check instance type availability\n• Verify AWS EC2 permissions\n• Ensure keypair exists\n• Try again or contact support"
    
    logger.info(f"📨 POPUP MESSAGE: {popup_msg}")
    await send_popup_only(
        user_email,
        f"{service_type} Deployment Failed",
        popup_msg,
        "error"
    )
    
    logger.info(f"🔔 BELL MESSAGE: {bell_message[:100]}...")
    await store_bell_notification(user_email, request_id, f"{service_type} Failed - {short_id}", bell_message, "error", {"error_message": error_message, "user_friendly_error": user_friendly_message, "service_type": service_type.lower(), "troubleshooting": True})

def parse_terraform_error(error_message: str) -> str:
    """Extract clean, user-friendly error message"""
    if not error_message:
        return "Deployment failed - unknown error"
    
    import re
    
    # Clean ANSI codes first
    clean_msg = re.sub(r'\[\d+m', '', error_message)
    
    # Extract specific AWS error patterns with user-friendly messages
    if "InvalidKeyPair.NotFound" in clean_msg:
        # Extract keypair name if available
        keypair_match = re.search(r"key pair '([^']+)'", clean_msg)
        if keypair_match:
            return f"SSH keypair '{keypair_match.group(1)}' not found. Please create it first or use existing keypair."
        return "SSH keypair not found. Please create a keypair or use existing one."
    
    if "InvalidSubnet.NotFound" in clean_msg:
        return "Selected subnet not found. Please choose a different subnet."
    
    if "InvalidGroup.NotFound" in clean_msg:
        return "Security group not found. Please select a valid security group."
    
    if "UnauthorizedOperation" in clean_msg:
        return "AWS permission denied. Contact your administrator for access."
    
    if "InvalidInstanceType" in clean_msg:
        return "Instance type not available in this region. Try a different type."
    
    if "InsufficientInstanceCapacity" in clean_msg:
        return "AWS capacity unavailable. Try different instance type or region."
    
    if "InvalidAMI.NotFound" in clean_msg:
        return "Operating system image not found. Contact support."
    
    if "InvalidVpc.NotFound" in clean_msg:
        return "VPC not found. Please select a valid VPC."
    
    # Extract EC2 API errors
    ec2_error = re.search(r'operation error EC2[^,]+, (.+?)(?:,|$)', clean_msg)
    if ec2_error:
        return f"AWS Error: {ec2_error.group(1).strip()}"
    
    # Extract general API errors
    api_error = re.search(r'api error ([^:]+): (.+?)(?:\n|\[|$)', clean_msg)
    if api_error:
        return f"AWS {api_error.group(1)}: {api_error.group(2).strip()}"
    
    # Extract Terraform errors
    terraform_error = re.search(r'Error: (.+?)(?:\n|\[|$)', clean_msg)
    if terraform_error:
        error_text = terraform_error.group(1).strip()
        # Limit length and clean up
        if len(error_text) > 100:
            error_text = error_text[:100] + "..."
        return error_text
    
    # Fallback for unknown errors
    return "Deployment failed - check configuration and try again"

async def send_destroy_notifications(user_email: str, request_id: str):
    """Send resource destruction notifications - WebSocket popup + Database storage"""
    short_id = request_id.split('_')[-1]
    
    # WebSocket → Popup (temporary snackbar)
    await send_popup_only(
        user_email,
        "Resources Destroyed",
        f"Infrastructure {short_id} has been destroyed successfully",
        "info"
    )
    
    # Database → Bell notification (persistent)
    await store_bell_notification(
        user_email,
        request_id,
        f"Infrastructure Destroyed - {short_id}",
        f"Your infrastructure resources for request {short_id} have been successfully destroyed and are no longer running.",
        "info",
        {"destroyed_at": datetime.now(timezone.utc).isoformat()}
    )

async def store_bell_notification(user_email: str, request_id: str, title: str, message: str, 
                                 status: str, details: Dict[str, Any]):
    """Store bell notification in database ONLY - NO WebSocket"""
    session = None
    try:
        logger.info(f"💾 STORING BELL NOTIFICATION:")
        logger.info(f"   User: {user_email}")
        logger.info(f"   Request: {request_id}")
        logger.info(f"   Title: {title}")
        logger.info(f"   Status: {status}")
        logger.info(f"   Details keys: {list(details.keys()) if details else 'None'}")
        
        session = AsyncSessionLocal()
        
        # Get user
        user_result = await session.execute(select(User).where(User.email == user_email))
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"User not found: {user_email}")
            return
        
        # Get request (optional)
        request_result = await session.execute(
            select(InfrastructureRequest).where(InfrastructureRequest.request_identifier == request_id)
        )
        request = request_result.scalar_one_or_none()
        
        # Check for duplicates
        global notification_cache
        cache_key = f"{user_email}:{request_id}:{status}:{title}"
        current_time = datetime.now(timezone.utc)
        
        if cache_key in notification_cache:
            last_time = notification_cache[cache_key]
            if (current_time - last_time).total_seconds() < 60:
                logger.info(f"😫 Skipping duplicate bell notification: {cache_key}")
                return
        
        notification_cache[cache_key] = current_time
        
        # Clean old cache entries
        cutoff_time = current_time - timedelta(hours=1)
        notification_cache = {k: v for k, v in notification_cache.items() if v > cutoff_time}
        
        # Create notification
        notification = UserNotification(
            user_id=user.id,
            request_id=request.id if request else uuid.uuid4(),
            notification_type="deployment",
            title=title,
            message=message,
            status=status,
            deployment_details=details,
            is_read=False
        )
        
        session.add(notification)
        await session.commit()
        logger.info(f"✅ Bell notification stored in database: {title}")
        logger.info(f"   Database ID: {notification.id}")
        logger.info(f"   Deployment details stored: {bool(details)}")
        
    except Exception as e:
        logger.error(f"❌ Failed to store bell notification: {e}")
        if session:
            await session.rollback()
    finally:
        if session:
            await session.close()