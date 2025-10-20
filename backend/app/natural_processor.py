import os
import json
import logging
import requests
from typing import Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class NaturalProcessor:
    def __init__(self):
        self.context_files = {}
        self.service_resolved = {}
        self.resolved_services = {}
        
    def _get_context_file_path(self, user_email: str) -> str:
        """Get context file path for user"""
        safe_email = user_email.replace('@', '_').replace('.', '_')
        return f"./context_{safe_email}.txt"
    
    def _save_to_context_file(self, user_email: str, role: str, content: str):
        """Save conversation to context file"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            context_entry = f"[{timestamp}] {role.upper()}: {content}\n"
            
            context_file = self._get_context_file_path(user_email)
            with open(context_file, "a", encoding="utf-8") as f:
                f.write(context_entry)
        except Exception as e:
            logger.error(f"Error saving to context file for {user_email}: {e}")
    
    def _load_context_from_file(self, user_email: str) -> str:
        """Load existing context from file"""
        try:
            context_file = self._get_context_file_path(user_email)
            if os.path.exists(context_file):
                with open(context_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return ""
        except Exception as e:
            logger.error(f"Error loading context file for {user_email}: {e}")
            return ""
    
    def clear_history(self, user_email: str):
        """Clear conversation history for user"""
        try:
            context_file = self._get_context_file_path(user_email)
            if os.path.exists(context_file):
                os.remove(context_file)
            
            if user_email in self.service_resolved:
                del self.service_resolved[user_email]
            if user_email in self.resolved_services:
                del self.resolved_services[user_email]
                
            logger.info(f"Cleared history for {user_email}")
        except Exception as e:
            logger.error(f"Error clearing history for {user_email}: {e}")
    
    def is_aws_request(self, user_email: str, user_input: str) -> Tuple[bool, Dict]:
        """Check if user input is AWS-related request with enhanced service detection"""
        
        # Save user input to context
        self._save_to_context_file(user_email, "user", user_input)
        
        # Simple pattern matching for AWS services
        user_input_lower = user_input.lower()
        
        # EC2 patterns - enhanced
        ec2_keywords = ["ec2", "instance", "server", "vm", "virtual machine", "compute", "ubuntu", "amazon linux", "windows server"]
        if any(word in user_input_lower for word in ec2_keywords):
            if any(word in user_input_lower for word in ["create", "deploy", "launch", "provision", "setup", "need", "want"]):
                self.service_resolved[user_email] = True
                self.resolved_services[user_email] = "ec2"
                return True, {
                    "category": "aws_specific",
                    "detected_service": "ec2",
                    "ready_for_analysis": True,
                    "response_message": "I'll help you create an EC2 instance. This will create a PR for approval first, then deploy after approval."
                }
        
        # S3 patterns - enhanced
        s3_keywords = ["s3", "bucket", "storage", "object storage", "file storage", "data storage"]
        if any(word in user_input_lower for word in s3_keywords):
            if any(word in user_input_lower for word in ["create", "deploy", "launch", "provision", "setup", "need", "want"]):
                self.service_resolved[user_email] = True
                self.resolved_services[user_email] = "s3"
                return True, {
                    "category": "aws_specific", 
                    "detected_service": "s3",
                    "ready_for_analysis": True,
                    "response_message": "I'll help you create an S3 bucket. This will create a PR for approval first, then deploy after approval."
                }
        
        # Lambda patterns - enhanced
        lambda_keywords = ["lambda", "function", "serverless", "aws lambda", "cloud function"]
        if any(word in user_input_lower for word in lambda_keywords):
            if any(word in user_input_lower for word in ["create", "deploy", "launch", "provision", "setup", "need", "want"]):
                self.service_resolved[user_email] = True
                self.resolved_services[user_email] = "lambda"
                return True, {
                    "category": "aws_specific",
                    "detected_service": "lambda", 
                    "ready_for_analysis": True,
                    "response_message": "I'll help you create a Lambda function. This will create a PR for approval first, then deploy after approval."
                }
        
        # General AWS questions
        if any(word in user_input_lower for word in ["aws", "amazon", "cloud"]):
            return True, {
                "category": "aws_general",
                "response_message": "I can help with AWS services like EC2 instances, S3 buckets, and Lambda functions. What would you like to create?"
            }
        
        # Not AWS related
        return False, {
            "category": "unrelated",
            "response_message": "I specialize in AWS infrastructure (EC2, S3, Lambda). How can I help with AWS services?"
        }
    
    async def handle_missing_parameters(self, user_email: str, current_config: Dict, missing_params: list) -> Dict:
        """Handle missing parameters naturally using OpenAI"""
        
        # Use OpenAI for natural missing parameter questions
        try:
            from .enhanced_genai_provider import EnhancedOpenAIProvider
            genai = EnhancedOpenAIProvider()
            
            prompt = f"""
User is configuring AWS infrastructure. Current configuration: {current_config}
Missing parameters: {missing_params}

Ask naturally for the next missing parameter in a conversational way.
Be helpful and guide the user to provide the needed information.

Respond with one natural, friendly question.
"""
            
            context = {
                "user_email": user_email,
                "current_config": current_config,
                "missing_params": missing_params
            }
            
            response = await genai.process_naturally(prompt, context)
            if response and response.get("response"):
                return {"message": response["response"].strip()}
            
        except Exception as e:
            logger.error(f"OpenAI missing parameters error: {e}")
        
        # If OpenAI fails, use a simple natural fallback
        missing_str = ", ".join(missing_params)
        return {
            "message": f"I need to know about: {missing_str}. Could you tell me what you'd like for these?"
        }
    
    async def get_cost_estimate(self, user_email: str, config: Dict) -> Dict:
        """Get cost estimate via MCP service"""
        try:
            response = requests.post(
                "http://localhost:8001/mcp/get-hourly-cost",
                json={
                    "instance_type": config.get("instance_type", "t3.micro"),
                    "region": config.get("region", "us-east-1"),
                    "operating_system": config.get("operating_system", "ubuntu")
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                cost_data = response.json()
                hourly_cost = cost_data.get("hourly_cost", 0)
                monthly_cost = cost_data.get("monthly_cost", 0)
                
                return {
                    "message": f"💰 Estimated cost: ${hourly_cost}/hour (${monthly_cost}/month)"
                }
            else:
                return {"message": "Cost estimation unavailable"}
                
        except Exception as e:
            logger.error(f"Cost estimation error: {e}")
            return {"message": "Cost estimation unavailable"}
    
    def is_service_resolved(self, user_email: str) -> Tuple[bool, str]:
        """Check if service is resolved for user"""
        resolved = self.service_resolved.get(user_email, False)
        service = self.resolved_services.get(user_email, None)
        return resolved, service