import logging
import json
import re
import os
import httpx
from typing import Dict, Any, List, Optional
import openai
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv
from .natural_processor import NaturalProcessor

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class EnhancedOpenAIProvider:
    def __init__(self):
        # Use ONLY Azure OpenAI
        azure_key = os.getenv('AZURE_OPENAI_API_KEY')
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        
        if not azure_key or not azure_endpoint:
            raise ValueError("Azure OpenAI credentials required. Please set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT.")
        
        self.client = AsyncAzureOpenAI(
            api_key=azure_key,
            api_version=os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview'),
            azure_endpoint=azure_endpoint
        )
        self.model_name = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o')
        self.use_openai = False
        self.natural_processor = NaturalProcessor()
        logger.info(f"✅ Using Azure OpenAI API with model: {self.model_name}")
        
    async def process_naturally(self, user_message: str, context: Dict) -> Dict[str, Any]:
        """Process user message using natural processor with context.txt approach"""
        
        logger.info(f"Processing message: {user_message}")
        
        # Extract user email from context
        user_email = context.get("user_name", "unknown@example.com")
        
        # Use natural processor for AWS detection
        is_aws, analysis = self.natural_processor.is_aws_request(user_email, user_message)
        
        if not is_aws:
            return {
                "intent": "unrelated",
                "response": analysis.get("response_message", "I'm here to help with AWS infrastructure!"),
                "parameters_detected": {},
                "actions": []
            }
        
        # Handle AWS service requests
        if analysis.get("ready_for_analysis"):
            service_type = analysis.get("detected_service", "ec2")
            
            # Analyze the request with validation
            analysis_result = await self.natural_processor.analyze_request_with_validation(
                user_email, user_message, service_type
            )
            
            if analysis_result.get("status") == "validation_error":
                return {
                    "intent": "os_validation",
                    "response": analysis_result.get("text"),
                    "parameters_detected": {},
                    "actions": ["collect_missing"]
                }
            
            # Extract parameters from analysis
            sample_config = analysis_result.get("sample_config", {})
            
            # Determine intent based on service type
            if service_type == "ec2":
                intent = "ec2_creation"
            elif service_type == "s3":
                intent = "s3_creation"
            elif service_type == "lambda":
                intent = "lambda_creation"
            else:
                intent = "ec2_creation"  # Default
            
            return {
                "intent": intent,
                "service_type": service_type,
                "response": analysis_result.get("text", "I'll help you create that AWS resource."),
                "parameters_detected": sample_config,
                "actions": ["create_resource"],
                "needs_validation": False
            }
        
        # Service needs clarification
        return {
            "intent": "unrelated",
            "response": analysis.get("response_message", "What AWS service would you like to create?"),
            "parameters_detected": {},
            "actions": []
        }
    
    async def analyze_message(self, message: str, context: Dict, user_info: Dict) -> Dict[str, Any]:
        """Analyze message using natural processor - main entry point for llm_processor"""
        return await self.process_naturally(message, context)
    
    async def _validate_os_region(self, os_type: str, region: str) -> Dict[str, Any]:
        """Validate OS availability in region via MCP service"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8001/mcp/validate-os-region",
                    json={"operating_system": os_type, "region": region},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"MCP validation failed: {response.status_code}")
                    return {"valid": True}  # Fallback to allow
                    
        except Exception as e:
            logger.error(f"OS validation error: {e}")
            return {"valid": True}  # Fallback to allow
    
    def clear_user_context(self, user_email: str):
        """Clear conversation context for user"""
        self.natural_processor.clear_history(user_email)
        logger.info(f"Cleared context for user: {user_email}")
    
    def get_user_context(self, user_email: str) -> str:
        """Get conversation context for user"""
        return self.natural_processor._load_context_from_file(user_email)
    
    def is_service_resolved(self, user_email: str):
        """Check if service has been resolved for user"""
        return self.natural_processor.is_service_resolved(user_email)
    
    def _build_system_prompt(self, context: Dict) -> str:
        current_config = context.get("current_config", {})
        missing_params = context.get("missing_params", [])
        current_step = context.get("current_step", "initial")
        networking_step = context.get("networking_step", "")
        env_access = context.get("env_access", {})
        department = context.get("department", "Unknown")
        file_context = context.get("file_context", "")
        
        return f"""You are an AWS specialist with comprehensive natural conversation abilities.

CURRENT CONTEXT:
- User config: {current_config}
- Missing: {missing_params}
- Step: {current_step}
- Networking Step: {networking_step}
- Environment access: {env_access}
- Department: {department}

PREVIOUS CONVERSATION CONTEXT:
{file_context[-1000:] if file_context else "No previous context"}

Respond naturally and handle all scenarios through pure language understanding."""