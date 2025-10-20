import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FRONTEND_URL

logger = logging.getLogger(__name__)

BACKEND_URL = "http://localhost:8000"

async def send_otp_email(to_email: str, otp: str):
    try:
        subject = "AIOps Platform - Login OTP"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
                <div style="background: #2c3e50; padding: 20px; color: white;">
                    <h2>AIOps Platform</h2>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p>Your login OTP:</p>
                    <div style="background: white; padding: 15px; text-align: center; border-radius: 5px;">
                        <h1 style="color: #2c3e50; margin: 0;">{otp}</h1>
                    </div>
                    <p style="font-size: 12px; color: #666;">Expires in 10 minutes</p>
                </div>
            </body>
        </html>
        """
        
        await send_email(to_email, subject, html_body)
        logger.info(f"OTP email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")
        return False

async def send_environment_approval_email(manager_email: str, user_name: str, user_department: str, environment: str, approval_token: str):
    try:
        approve_link = f"{BACKEND_URL}/environment/approve/{approval_token}"
        deny_link = f"{BACKEND_URL}/environment/deny/{approval_token}"
        subject = f"Environment Access Request - {user_name} ({environment.upper()})"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
                <div style="background: #2c3e50; padding: 20px; color: white;">
                    <h3>AIOps Platform - Access Request</h3>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p><strong>{user_name}</strong> from <strong>{user_department}</strong> is requesting access to <strong>{environment.upper()}</strong> environment.</p>
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{approve_link}" style="background: #27ae60; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-right: 10px;">Approve</a>
                        <a href="{deny_link}" style="background: #e74c3c; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Deny</a>
                    </div>
                    
                    <p style="font-size: 12px; color: #666;">Request expires in 24 hours</p>
                </div>
            </body>
        </html>
        """
        
        await send_email(manager_email, subject, html_body)
        return True
    except Exception as e:
        logger.error(f"Failed to send approval email: {e}")
        return False

async def send_access_granted_email(user_email: str, user_name: str, environment: str, approved_by: str):
    try:
        subject = f"AIOps Platform - Access Granted ({environment.upper()})"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
                <div style="background: #27ae60; padding: 20px; color: white;">
                    <h3>Access Granted</h3>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p>Hi {user_name},</p>
                    <p>Your access to <strong>{environment.upper()}</strong> environment has been approved by {approved_by}.</p>
                    <p>You can now access the environment through the platform.</p>
                    <div style="text-align: center; margin: 15px 0;">
                        <a href="{FRONTEND_URL}/dashboard" style="background: #2c3e50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Access Dashboard</a>
                    </div>
                </div>
            </body>
        </html>
        """
        
        await send_email(user_email, subject, html_body)
        return True
    except Exception as e:
        logger.error(f"Failed to send access granted email: {e}")
        return False

async def send_access_denied_email(user_email: str, user_name: str, environment: str, denied_by: str, reason: str = None):
    try:
        subject = f"AIOps Platform - Access Denied ({environment.upper()})"
        
        reason_text = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
                <div style="background: #e74c3c; padding: 20px; color: white;">
                    <h3>Access Request Update</h3>
                </div>
                <div style="padding: 20px; background: #f9f9f9;">
                    <p>Hi {user_name},</p>
                    <p>Your request for <strong>{environment.upper()}</strong> environment access has been denied by {denied_by}.</p>
                    {reason_text}
                    <p>Contact your manager or support for more information.</p>
                </div>
            </body>
        </html>
        """
        
        await send_email(user_email, subject, html_body)
        return True
    except Exception as e:
        logger.error(f"Failed to send access denied email: {e}")
        return False

async def send_email(to_email: str, subject: str, html_body: str):
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.info(f"Email would be sent to {to_email}: {subject}")
        logger.info(f"Email content: {html_body}")
        return
        
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"AIOps Platform <{SMTP_USERNAME}>"
    msg['To'] = to_email
    
    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)
    
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    server.send_message(msg)
    server.quit()