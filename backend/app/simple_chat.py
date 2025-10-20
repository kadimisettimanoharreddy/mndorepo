from fastapi import APIRouter, HTTPException
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/simple-test")
async def simple_chat_test(request: dict):
    """Simple chat test without authentication for testing purposes"""
    try:
        message = request.get("message", "")
        if not message:
            return {"response": "Please provide a message"}
        
        # Simple pattern-based responses for testing
        message_lower = message.lower()
        
        # Cost estimation
        if any(word in message_lower for word in ["cost", "price", "expensive", "cheap"]):
            if "t3.micro" in message_lower:
                return {
                    "response": "💰 Estimated cost for t3.micro: Instance $8.50/month + Storage $2.00/month = $10.50/month",
                    "buttons": [],
                    "show_text_input": True
                }
            else:
                return {
                    "response": "💰 I can estimate costs for EC2 instances. Please specify instance type (e.g., t3.micro, t3.small)",
                    "buttons": [],
                    "show_text_input": True
                }
        
        # Multi-intent (create + cost)
        elif "create" in message_lower and "cost" in message_lower:
            return {
                "response": "Great! I see you want to create an instance and get cost estimates. For t3.micro Ubuntu: ~$10.50/month. Ready to configure?",
                "buttons": [{"text": "Configure Now", "value": "configure"}],
                "show_text_input": True
            }
        
        # AWS service questions
        elif "s3" in message_lower and any(word in message_lower for word in ["what", "tell", "explain"]):
            return {
                "response": "**Amazon S3** is object storage for files, backups, and static websites. You can create buckets, upload files, and set permissions through the AWS Console.\n\nNeed help creating an EC2 instance?",
                "buttons": [{"text": "Yes, Create EC2", "value": "yes create ec2"}, {"text": "Not Now", "value": "no thanks"}],
                "show_text_input": True
            }
        
        elif "difference" in message_lower and "s3" in message_lower and "ebs" in message_lower:
            return {
                "response": "**S3 vs EBS:**\n\n**Amazon S3** - Object storage:\n• Internet-accessible file storage\n• Unlimited capacity\n• Access via REST API/web\n\n**Amazon EBS** - Block storage:\n• Attached to EC2 instances\n• Like a hard drive for your server\n• High performance for databases\n\nNeed help creating an EC2 instance?",
                "buttons": [{"text": "Yes, Create EC2", "value": "yes create ec2"}],
                "show_text_input": True
            }
        
        # Unrelated questions
        elif "lunch" in message_lower:
            return {
                "response": "Enjoy your lunch! 🍽️ I'll be here when you get back to help with your AWS infrastructure needs.",
                "buttons": [],
                "show_text_input": True
            }
        
        elif any(cloud in message_lower for cloud in ["google cloud", "gcp", "azure"]):
            cloud_name = "Google Cloud" if any(g in message_lower for g in ["google", "gcp"]) else "Azure"
            return {
                "response": f"I'm focused on AWS services. For {cloud_name}, you'd need their respective platforms. Want to create an AWS EC2 instance?",
                "buttons": [{"text": "Yes, Create EC2", "value": "yes create ec2"}],
                "show_text_input": True
            }
        
        # Non-EC2 services
        elif any(service in message_lower for service in ["s3 bucket", "lambda", "rds", "dynamodb"]) and "create" in message_lower:
            service_name = "S3" if "s3" in message_lower else "Lambda" if "lambda" in message_lower else "RDS" if "rds" in message_lower else "DynamoDB"
            return {
                "response": f"I specialize in EC2 instances. For {service_name}, please use the AWS Console or specific service documentation. Need help creating an EC2 instance?",
                "buttons": [{"text": "Yes, Create EC2", "value": "yes create ec2"}],
                "show_text_input": True
            }
        
        # Parameter changes
        elif "change" in message_lower and "t3.large" in message_lower:
            return {
                "response": "Updated instance type to t3.large. This will cost approximately $67/month. Ready to configure networking?",
                "buttons": [{"text": "Configure Networking", "value": "networking"}],
                "show_text_input": True
            }
        
        # Complex requests
        elif "machine learning" in message_lower and "t3.medium" in message_lower:
            return {
                "response": "Perfect for machine learning! I've configured t3.medium with 50GB storage for ML workloads. For PROD environment, you'll need approval. Should I request it?",
                "buttons": [{"text": "Request PROD Access", "value": "request prod"}, {"text": "Use DEV Instead", "value": "use dev"}],
                "show_text_input": True
            }
        
        # EC2 creation
        elif any(word in message_lower for word in ["create", "deploy", "instance", "server"]):
            return {
                "response": "Great! I'd love to help you create an EC2 instance. What are your requirements? (instance type, OS, environment, etc.)",
                "buttons": [],
                "show_text_input": True
            }
        
        # Default response
        else:
            return {
                "response": "I'm here to help you create AWS EC2 instances! What would you like to build today?",
                "buttons": [],
                "show_text_input": True
            }
            
    except Exception as e:
        logger.error(f"Simple chat test error: {e}")
        return {
            "response": f"Error processing message: {str(e)}",
            "buttons": [],
            "show_text_input": True
        }