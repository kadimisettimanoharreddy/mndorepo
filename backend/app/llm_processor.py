import logging
import re
import asyncio
from typing import Dict, Any, List, Optional
import httpx

from .enhanced_genai_provider import EnhancedOpenAIProvider
from .confirmation_manager import ConfirmationManager
from .permissions import get_department_limits, check_environment_access, can_create_resource

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {
    "update_parameters","estimate_cost","launch","request_access","ask_info","smalltalk",
    "other_service","multi_intent","general_knowledge","networking","cancel","none"
}
ALLOWED_ACTIONS = {
    "update_parameters","estimate_cost","launch_environment","request_environment_access","answer",
    "suggest_environment","cancel_request",
    "start_networking","use_default_networking","choose_existing_vpc","select_vpc","confirm_vpc",
    "select_subnet","confirm_subnet","select_security_group","confirm_security_group",
    "set_keypair","approve_security","deploy_now","cancel_deploy"
}
REQ_FIELDS = ["environment","instance_type","operating_system","storage_size","region"]
ENV_ORDER = ["dev", "qa", "prod"]

class LLMProcessor:
    def __init__(self):
        self.provider = EnhancedOpenAIProvider()
        self.confirmation_manager = ConfirmationManager()
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.conversation_states: Dict[str, Dict[str, Any]] = {}
        self.user_context: Dict[str, Dict[str, Any]] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
    
    def clear_user_session(self, user_email: str):
        """Clear all session data for a user - called on fresh login"""
        if user_email in self.conversations:
            del self.conversations[user_email]
        if user_email in self.conversation_states:
            del self.conversation_states[user_email]
        if user_email in self.user_context:
            del self.user_context[user_email]
        if user_email in self.locks:
            del self.locks[user_email]
        
        # Clear any pending confirmations
        self.confirmation_manager.clear_pending_confirmation(user_email)
        
        # Initialize fresh state
        self._initialize_user_state(user_email, preserve_conversation=False)
        
        logger.info(f"COMPLETE SESSION CLEAR: {user_email} - All data cleared for fresh login")

    async def process_user_message(self, user_email: str, message: str, user_info: Dict) -> Dict[str, Any]:
        if user_email not in self.locks:
            self.locks[user_email] = asyncio.Lock()
        if self.locks[user_email].locked():
            return {"message": "Processing...", "show_text_input": True}
        async with self.locks[user_email]:
            if user_email not in self.conversations:
                self._initialize_user_state(user_email, preserve_conversation=True)
            return await self._process_message(user_email, message, user_info)

    def _initialize_user_state(self, user_email: str, preserve_conversation: bool = False):
        if user_email not in self.conversations:
            self.conversations[user_email] = []
        elif not preserve_conversation:
            self.conversations[user_email] = []
        
        # ALWAYS reset parameters and state for fresh start
        self.conversation_states[user_email] = {
            "collected_parameters": {},
            "missing_parameters": REQ_FIELDS.copy(),
            "current_step": "initial",
            "has_active_request": False,
        }
        self.user_context[user_email] = {"step": "initial", "config": {}, "lists": {}}
        
        # Clear any pending confirmations
        self.confirmation_manager.clear_pending_confirmation(user_email)
        
        # Clear networking preferences
        if user_email in self.user_context and "networking_preference" in self.user_context[user_email]:
            del self.user_context[user_email]["networking_preference"]
        
        logger.info(f"USER STATE RESET: {user_email} - Fresh start with empty parameters (preserve_conversation: {preserve_conversation})")

    def _build_context(self, user_email: str, user_info: Dict) -> Dict:
        state = self.conversation_states.get(user_email, {})
        return {
            "user_name": user_info.get("name", "User"),
            "department": user_info.get("department", "Unknown"),
            "current_config": state.get("collected_parameters", {}),
            "missing_params": state.get("missing_parameters", []),
            "conversation": self.conversations.get(user_email, [])[-12:],
            "env_access": user_info.get("environment_access", {}),
            "env_expiry": user_info.get("environment_expiry", {}),
            "current_step": state.get("current_step", "initial"),
            "has_active_request": state.get("has_active_request", False),
            "networking_step": self.user_context.get(user_email, {}).get("step", "")
        }

    async def _process_message(self, user_email: str, message: str, user_info: Dict) -> Dict[str, Any]:
        msg = message.strip()
        state = self.conversation_states[user_email]
        
        # Handle refresh/cancel commands
        if msg.upper() in ["REFRESH", "CANCEL", "CLEAR", "RESET"]:
            self._initialize_user_state(user_email, preserve_conversation=False)
            return {"message": "Starting fresh! What can I help you build today?", "show_text_input": True}
        
        # Skip empty messages - frontend handles greetings
        if not msg:
            return {"message": "What would you like to create today?", "show_text_input": True}
        
        # Handle deployment completion - reset state and be ready for new requests
        if state.get("has_active_request") and any(word in msg.lower() for word in ["deployed", "ready", "complete", "finished"]):
            self._initialize_user_state(user_email, preserve_conversation=False)
            return {"message": "Great! Your infrastructure is ready. What else would you like to create today?", "show_text_input": True}
        
        # Use OpenAI provider to check if this is AWS-related first
        is_aws_request = await self._is_aws_request(user_email, msg, user_info)
        
        if not is_aws_request:
            # Handle non-AWS requests directly
            return {
                "message": "I specialize in AWS infrastructure (EC2 instances, S3 buckets, Lambda functions). How can I help with AWS services?",
                "show_text_input": True
            }
        
        # Detect NEW infrastructure requests - should start fresh
        new_request_phrases = ["i want to create", "create instance", "create new", "new instance", "i need", "deploy new", "i want instance", "need instance"]
        update_phrases = ["change", "update", "modify", "switch", "replace"]
        
        if any(phrase in msg.lower() for phrase in new_request_phrases):
            # Check if this is truly a new request (not just parameter update)
            if not any(word in msg.lower() for word in update_phrases):
                logger.info(f"NEW REQUEST DETECTED: {msg} - Starting fresh")
                self._initialize_user_state(user_email, preserve_conversation=False)
        
        if user_email not in self.conversations:
            self.conversations[user_email] = []
        if msg:
            self.conversations[user_email].append({"role": "user", "content": msg})

        # ALWAYS use natural language processing with OpenAI for ALL scenarios
        logger.info(f"Processing message with OpenAI: {msg}")
        return await self._process_natural_conversation(user_email, msg, user_info)

    async def _is_aws_request(self, user_email: str, message: str, user_info: Dict) -> bool:
        """Use OpenAI provider to determine if this is an AWS-related request"""
        context = self._build_context(user_email, user_info)
        
        # Use a simple prompt to check if this is AWS-related
        check_prompt = f"""
        Determine if this user message is about AWS infrastructure or services.
        Message: "{message}"
        
        Respond with ONLY "true" if it's AWS-related (EC2, S3, Lambda, VPC, networking, instances, etc.)
        Respond with ONLY "false" if it's about other cloud providers, personal questions, or unrelated topics.
        """
        
        try:
            # Use the provider's direct processing for simple classification
            response = await self.provider.process_naturally(message, context)
            intent = response.get("intent", "")
            
            # Check if it's AWS-related based on intent and service
            aws_intents = ["ec2_creation", "s3_creation", "lambda_creation", "networking_config", 
                          "parameter_update", "cost_estimation", "environment_request", "deploy"]
            service = response.get("service", "").lower()
            
            if intent in aws_intents or "aws" in service or "ec2" in service or "s3" in service or "lambda" in service:
                return True
            elif intent in ["unrelated", "non_aws", "gcp_related", "azure_related", "other_cloud", "personal_question"]:
                return False
            else:
                # Default to true for general AWS questions
                return "aws" in message.lower() or any(word in message.lower() for word in 
                                                      ["ec2", "instance", "s3", "bucket", "lambda", "vpc", "subnet", "security group"])
                
        except Exception as e:
            logger.error(f"Error checking AWS request: {e}")
            # Fallback to keyword matching if OpenAI fails
            aws_keywords = ["aws", "ec2", "instance", "s3", "bucket", "lambda", "vpc", "subnet", 
                           "security group", "cloud", "server", "deploy", "create", "launch"]
            return any(keyword in message.lower() for keyword in aws_keywords)

    def _sanitize_schema(self, ai: Dict[str, Any]) -> Dict[str, Any]:
        intent = ai.get("intent", "none")
        if intent not in ALLOWED_INTENTS:
            intent = "none"
        actions = [a for a in ai.get("actions", []) if a in ALLOWED_ACTIONS]
        params = ai.get("parameters_detected") or {}
        suggestion = ai.get("suggestion") or {}
        buttons = ai.get("buttons") if isinstance(ai.get("buttons"), list) else []
        
        safe = {
            "intent": intent,
            "topic": ai.get("topic", "unknown"),
            "cloud_provider": ai.get("cloud_provider", "unknown"),
            "service": ai.get("service", "unknown"),
            "resource_type": ai.get("resource_type", "unknown"),
            "response": ai.get("response", ""),
            "parameters_detected": {
                "environment": params.get("environment"),
                "instance_type": params.get("instance_type"),
                "operating_system": params.get("operating_system"),
                "storage_size": params.get("storage_size"),
                "region": params.get("region"),
                "target_env": params.get("target_env"),
                "user_choice": params.get("user_choice"),
                "vpc_mode": params.get("vpc_mode"),
                "selected_vpc_id": params.get("selected_vpc_id"),
                "subnet_mode": params.get("subnet_mode"),
                "selected_subnet_id": params.get("selected_subnet_id"),
                "subnet_type": params.get("subnet_type"),
                "sg_mode": params.get("sg_mode"),
                "selected_sg_id": params.get("selected_sg_id"),
                "keypair_type": params.get("keypair_type"),
                "keypair_name": params.get("keypair_name"),
                "cost_scope": params.get("cost_scope"),
                "bucket_name": params.get("bucket_name"),
                "function_name": params.get("function_name"),
                "runtime": params.get("runtime"),
                "memory_size": params.get("memory_size"),
                "timeout": params.get("timeout"),
                "versioning_enabled": params.get("versioning_enabled"),
                "public_access": params.get("public_access"),
                "networking_preference": params.get("networking_preference"),
                "user_action": params.get("user_action"),
                "next_step": params.get("next_step")
            },
            "actions": actions,
            "buttons": [b for b in buttons if isinstance(b, dict) and "text" in b],
            "suggestion": {
                "suggest": bool(suggestion.get("suggest", False)),
                "environment": suggestion.get("environment"),
                "rationale": suggestion.get("rationale")
            }
        }
        for b in safe["buttons"]:
            if "value" not in b:
                b["value"] = b["text"].lower().replace(" ", "_")
        return safe

    async def _process_natural_conversation(self, user_email: str, message: str, user_info: Dict) -> Dict[str, Any]:
        """Natural conversation processing with enhanced OpenAI understanding - NO FALLBACKS"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        
        # Use enhanced OpenAI provider for ALL processing
        context = self._build_context(user_email, user_info)
        
        ai_response = await self.provider.process_naturally(message, context)
        logger.info(f"✅ OpenAI response received: {ai_response.get('intent')}")
        
        # Handle different intents naturally
        intent = ai_response.get("intent", "general_aws_question")
        params = ai_response.get("parameters_detected", {}) or {}
        response_text = ai_response.get("response", "")
        actions = ai_response.get("actions", []) or []
        
        logger.info(f"Processing intent: {intent}, params: {params}")
        
        # Handle networking flow FIRST - highest priority (existing functionality)
        if self.user_context[user_email]["step"] in ["networking_choice", "vpc_selection", "subnet_selection", "sg_selection", "keypair_selection", "keypair_name_input", "security_approval", "final_deploy"]:
            return await self._handle_networking_flow_enhanced(user_email, user_info, message, ai_response)
        
        # Handle pending confirmations (existing functionality)
        if self.confirmation_manager.has_pending_confirmation(user_email):
            return await self._handle_pending_confirmation(user_email, user_info, ai_response)
        
        # Control intents - handle all control actions (existing functionality)
        control_intents = ["cancel", "stop", "abort", "reset", "start_over", "clear"]
        
        if intent in control_intents:
            self.confirmation_manager.clear_pending_confirmation(user_email)
            self._initialize_user_state(user_email, preserve_conversation=False)
            return {"message": "All cleared! I'm ready to help you create something new. What would you like to build?", "show_text_input": True}
        
        # Handle unrelated and other cloud questions
        unrelated_intents = ["unrelated", "non_aws", "gcp_related", "azure_related", "other_cloud", "personal_question"]
        if intent in unrelated_intents:
            service = ai_response.get("service_mentioned", "").lower()
            if service in ["gcp", "google cloud", "azure", "microsoft azure"]:
                return {
                    "message": f"I specialize in AWS services. For {service.upper()}, you'd need their respective platforms. Want to create an AWS resource instead?",
                    "show_text_input": True
                }
            else:
                return {
                    "message": "I'm here to help with AWS EC2 instances, S3 buckets, and Lambda functions! What would you like to create?",
                    "show_text_input": True
                }
        
        # Handle non-EC2 AWS services
        non_ec2_intents = ["non_ec2_service", "other_aws_service", "create_rds"]
        if intent in non_ec2_intents:
            service = ai_response.get("service_mentioned", "").lower()
            if service in ["rds", "dynamodb", "sns", "sqs"]:
                return {
                    "message": f"I specialize in EC2 instances, S3 buckets, and Lambda functions. For {service.upper()}, please use the AWS Console or specific service documentation. Need help with EC2, S3, or Lambda?",
                    "show_text_input": True
                }
        
        # Handle AWS service info questions
        aws_info_intents = ["aws_service_info", "aws_concepts", "aws_best_practices"]
        if intent in aws_info_intents:
            # Provide helpful AWS information but redirect to creation
            return {
                "message": f"{response_text}\n\nNeed help creating an AWS resource?",
                "buttons": [
                    {"text": "Create EC2 Instance", "value": "create_ec2"},
                    {"text": "Create S3 Bucket", "value": "create_s3"},
                    {"text": "Create Lambda Function", "value": "create_lambda"}
                ],
                "show_text_input": True
            }
        
        # Handle service-specific creation intents
        creation_intents = ["ec2_creation", "s3_creation", "lambda_creation", "server_request", "application_deployment"]
        
        if intent in creation_intents:
            return await self._handle_service_creation_intent(user_email, user_info, ai_response, intent)
        
        # Handle parameter updates (existing functionality)
        parameter_intents = ["parameter_update", "region_selection", "environment_selection", "instance_type_selection", "storage_configuration", "operating_system_selection"]
        
        if intent in parameter_intents and params:
            return await self._handle_parameter_update_enhanced(user_email, user_info, ai_response)
        
        # Handle cost estimation (existing functionality)
        cost_intents = ["cost_estimation", "pricing_inquiry", "budget_planning"]
        
        if intent in cost_intents or ai_response.get("cost_request"):
            return await self._handle_cost_estimation_enhanced(user_email, user_info, ai_response)
        
        # Handle environment and approval requests (existing functionality)
        access_intents = ["environment_request", "approval_request", "access_request", "permission_request"]
        
        if intent in access_intents:
            return await self._handle_environment_request(user_email, user_info, ai_response)
        
        # Networking configuration (existing functionality)
        networking_intents = ["networking_config", "default_networking", "custom_networking", "vpc_setup"]
        
        if intent in networking_intents or intent == "confirmation_response" or ai_response.get("parameters_detected", {}).get("deployment_ready"):
            return await self._handle_networking_start(user_email, user_info)
        
        # Deploy intents (existing functionality)
        deploy_intents = ["deploy", "launch", "provision", "create_now", "start_deployment"]
        
        if intent in deploy_intents:
            return await self._handle_deploy_intent(user_email, user_info)
        
        # Query intents (existing functionality)
        query_intents = ["allowed_values_query", "technical_specifications", "resource_limits", "capability_inquiry"]
        
        if intent in query_intents:
            return await self._handle_allowed_values_query(user_email, user_info, ai_response)
        
        # Confirmation responses (existing functionality)
        confirmation_intents = ["confirmation_response", "positive_response", "negative_response", "conditional_response"]
        
        if intent in confirmation_intents:
            if self.confirmation_manager.has_pending_confirmation(user_email):
                return await self._handle_pending_confirmation(user_email, user_info, ai_response)
            else:
                # No pending confirmation, user is confirming to proceed with deployment
                return await self._handle_networking_start(user_email, user_info)
        
        # Multi-intent handling
        if intent == "multi_intent":
            return await self._handle_multi_intent_enhanced(user_email, user_info, ai_response)
        
        # General AWS questions - use OpenAI response directly
        if intent == "general_aws_question":
            # Check if we have existing configuration to provide context
            if cfg:
                missing = self._get_missing(cfg)
                if missing:
                    service_type = cfg.get("service_type", "resource")
                    return {
                        "message": f"{response_text}\n\nContinuing with your {service_type} configuration. Still need: {', '.join(missing)}",
                        "show_text_input": True
                    }
            
            return {"message": response_text, "show_text_input": True}
        
        # Default response - use OpenAI response directly
        return {"message": response_text, "show_text_input": True}

    async def _handle_service_creation_intent(self, user_email: str, user_info: Dict, ai_response: Dict, intent: str) -> Dict[str, Any]:
        """Handle service creation intent (EC2, S3, Lambda)"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        params = ai_response.get("parameters_detected", {})
        
        # Determine service type
        service_type = self._get_service_type_from_intent(intent)
        
        # Clear previous state if starting new service creation
        if service_type != cfg.get("service_type"):
            cfg.clear()
            cfg["service_type"] = service_type
            state["missing_parameters"] = self._get_required_parameters(service_type)
            logger.info(f"Starting new {service_type} creation")
        
        # Update parameters with validation
        if params:
            update_result = self._update_parameters_smart(state, params, "direct", user_email, user_info)
            if update_result and update_result.startswith("validation_error:"):
                error_msg = update_result.replace("validation_error: ", "")
                return {
                    "message": f"❌ {error_msg}",
                    "show_text_input": True
                }
        
        # Check completion status
        missing = self._get_missing(cfg)
        
        if not missing:
            # All parameters collected - handle based on service type
            if service_type == "ec2":
                return await self._suggest_environment_smart(user_email, user_info, "Great! I've configured your EC2 instance.")
            elif service_type == "s3":
                bucket_name = cfg.get('bucket_name', 'your bucket')
                environment = cfg.get('environment', 'dev').upper()
                return {
                    "message": f"Perfect! S3 bucket '{bucket_name}' configured in {environment} environment. Ready to create it?",
                    "buttons": [
                        {"text": "Create S3 Bucket", "value": "create_s3"},
                        {"text": "Modify Configuration", "value": "modify"}
                    ],
                    "show_text_input": True
                }
            elif service_type == "lambda":
                function_name = cfg.get('function_name', 'your function')
                runtime = cfg.get('runtime', 'python3.9')
                return {
                    "message": f"Excellent! Lambda function '{function_name}' with {runtime} configured. Ready to deploy?",
                    "buttons": [
                        {"text": "Create Lambda Function", "value": "create_lambda"},
                        {"text": "Modify Configuration", "value": "modify"}
                    ],
                    "show_text_input": True
                }
        
        # Still missing parameters - provide contextual guidance
        if missing:
            missing_str = ", ".join(missing)
            current_service = cfg.get("service_type", "resource")
            
            # Service-specific guidance using OpenAI for better questions
            if service_type == "s3" and "bucket_name" in missing:
                question = await self._handle_missing_parameters(user_email, cfg, missing)
                return {"message": question.get("message", "What would you like to name your S3 bucket?"), "show_text_input": True}
            elif service_type == "lambda" and "function_name" in missing:
                question = await self._handle_missing_parameters(user_email, cfg, missing)
                return {"message": question.get("message", "What should your Lambda function be named?"), "show_text_input": True}
            
            # Use OpenAI for better missing parameter questions
            question = await self._handle_missing_parameters(user_email, cfg, missing)
            if question and question.get("message"):
                return {"message": question["message"], "show_text_input": True}
            
            return {
                "message": f"Great! I'm configuring your {current_service}. Still need: {missing_str}. What would you like to specify next?",
                "show_text_input": True
            }
        
        return {"message": "Let me know what you'd like to configure.", "show_text_input": True}

    async def _handle_missing_parameters(self, user_email: str, cfg: Dict, missing: List[str]) -> Dict[str, Any]:
        """Handle missing parameters using OpenAI for natural questions"""
        context = self._build_context(user_email, {})
        
        # Create a prompt for asking about missing parameters naturally
        prompt = f"""
        The user is configuring a {cfg.get('service_type', 'resource')} but missing these parameters: {', '.join(missing)}.
        Current configuration: {cfg}
        
        Ask a natural, helpful question to get one of the missing parameters. Be specific and helpful.
        """
        
        try:
            response = await self.provider.process_naturally(prompt, context)
            return {"message": response.get("response", f"What {missing[0]} would you like?")}
        except Exception as e:
            logger.error(f"Error generating missing parameter question: {e}")
            return {"message": f"What {missing[0]} would you like?"}

    def _get_service_type_from_intent(self, intent: str) -> str:
        """Map intent to service type"""
        if intent in ["ec2_creation", "server_request", "application_deployment"]:
            return "ec2"
        elif intent in ["s3_creation", "bucket_creation", "storage_creation"]:
            return "s3"
        elif intent in ["lambda_creation", "function_creation"]:
            return "lambda"
        return "ec2"  # default

    def _get_required_parameters(self, service_type: str) -> List[str]:
        """Get required parameters for each service type"""
        if service_type == "ec2":
            return ["environment", "instance_type", "operating_system", "storage_size", "region"]
        elif service_type == "s3":
            return ["bucket_name", "environment", "region"]
        elif service_type == "lambda":
            return ["function_name", "runtime", "environment", "region"]
        return []

    def _get_missing(self, cfg: Dict) -> List[str]:
        """Get missing parameters based on service type"""
        service_type = cfg.get("service_type", "ec2")
        required = self._get_required_parameters(service_type)
        return [param for param in required if param not in cfg or not cfg[param]]

    async def _handle_networking_flow_enhanced(self, user_email: str, user_info: Dict, message: str, ai_response: Dict = None) -> Dict[str, Any]:
        """Enhanced networking flow with natural language understanding"""
        step = self.user_context[user_email]["step"]
        msg_lower = message.lower().strip()
        
        # Use AI response if provided, otherwise process the message
        if ai_response:
            intent = ai_response.get("intent", "")
            params = ai_response.get("parameters_detected", {}) or {}
            user_action = params.get("user_action")
            next_step = params.get("next_step")
        else:
            # Process with OpenAI if no AI response provided
            context = self._build_context(user_email, user_info)
            ai_response = await self.provider.process_naturally(message, context)
            intent = ai_response.get("intent", "")
            params = ai_response.get("parameters_detected", {}) or {}
            user_action = params.get("user_action")
            next_step = params.get("next_step")
        
        logger.info(f"Networking flow - Step: {step}, Intent: {intent}, User Action: {user_action}, Next Step: {next_step}")
        
        # Handle networking progression based on AI understanding
        if step == "networking_choice":
            if user_action == "proceed" or intent in ["default_networking", "networking_config"]:
                if params.get("networking_preference") == "default" or "default" in msg_lower:
                    return await self._handle_default_vpc_flow(user_email, user_info)
                else:
                    return await self._handle_existing_vpc_flow(user_email, user_info)
        
        elif step == "vpc_selection":
            if user_action == "proceed" and params.get("selected_vpc_id"):
                return await self._handle_vpc_choice(user_email, user_info, params.get("selected_vpc_id"))
            elif user_action == "go_back":
                return await self._handle_existing_vpc_flow(user_email, user_info)
        
        elif step == "subnet_selection":
            if user_action == "proceed" and params.get("selected_subnet_id"):
                return await self._handle_subnet_choice(user_email, user_info, params.get("selected_subnet_id"))
            elif user_action == "go_back":
                return await self._handle_vpc_choice(user_email, user_info, self.user_context[user_email]["config"].get("vpc_id"))
        
        elif step == "sg_selection":
            if user_action == "proceed":
                sg_choice = params.get("selected_sg_id") or "default"
                return await self._handle_sg_choice(user_email, user_info, sg_choice)
            elif user_action == "go_back":
                return await self._handle_subnet_choice(user_email, user_info, self.user_context[user_email]["config"].get("subnet_id"))
        
        elif step == "keypair_selection":
            if user_action == "proceed":
                if params.get("keypair_type") == "new" or "create new" in msg_lower:
                    self.user_context[user_email]["step"] = "keypair_name_input"
                    return {
                        "message": "What would you like to name your new keypair? (letters, numbers, hyphens only):",
                        "show_text_input": True
                    }
                else:
                    keypair_name = params.get("keypair_name") or "use existing"
                    return await self._handle_keypair_choice(user_email, user_info, keypair_name)
            elif user_action == "go_back":
                return await self._handle_sg_choice(user_email, user_info, self.user_context[user_email]["config"].get("sg_id"))
        
        elif step == "keypair_name_input":
            return await self._handle_keypair_name_input(user_email, user_info, message.strip())
        
        elif step == "security_approval":
            if user_action == "proceed" or intent in ["positive_response", "confirmation_response"]:
                return await self._show_final_approval(user_email, user_info)
            elif user_action == "go_back":
                return await self._handle_keypair_choice(user_email, user_info, "change")
        
        elif step == "final_deploy":
            if user_action == "proceed" or intent in ["positive_response", "confirmation_response", "deploy"]:
                return await self._execute_deployment(user_email, user_info)
            elif user_action == "go_back":
                return await self._show_security_approval(user_email, user_info)
        
        # Provide step-specific guidance if nothing matched
        return await self._provide_networking_guidance(user_email, step)

    async def _provide_networking_guidance(self, user_email: str, step: str) -> Dict[str, Any]:
        """Provide contextual guidance for networking steps"""
        if step == "networking_choice":
            return {
                "message": "Choose your networking setup:\n\n• **Default VPC** - Quick setup with AWS defaults\n• **Existing VPC** - Choose from your existing VPCs\n\nWhich would you prefer?",
                "buttons": [{"text": "Use Default", "value": "default vpc"}, {"text": "Use Existing", "value": "existing vpc"}],
                "show_text_input": True
            }
        elif step == "vpc_selection":
            vpcs = self.user_context[user_email].get("available_vpcs", [])
            if vpcs:
                vpc_list = "\n".join([f"• {vpc['id']} - {vpc['cidr']} ({'default' if vpc.get('is_default') else 'custom'})" for vpc in vpcs[:5]])
                return {
                    "message": f"Available VPCs:\n\n{vpc_list}\n\nSelect a VPC by clicking or typing the VPC ID:",
                    "show_text_input": True
                }
        elif step == "subnet_selection":
            subnets = self.user_context[user_email].get("available_subnets", [])
            if subnets:
                subnet_list = "\n".join([f"• {s['id']} - {s.get('cidr', 'N/A')} ({'public' if s.get('public') else 'private'})" for s in subnets[:5]])
                return {
                    "message": f"Available Subnets:\n\n{subnet_list}\n\nSelect a subnet by clicking or typing the subnet ID:",
                    "show_text_input": True
                }
        elif step == "sg_selection":
            return {
                "message": "Choose security group:\n\n• **Default** - SSH, HTTP, HTTPS access\n• **Existing** - Choose from your security groups\n\nType 'default' or select from the list:",
                "show_text_input": True
            }
        elif step == "keypair_selection":
            return {
                "message": "Choose keypair for SSH access:\n\n• **Create New Keypair** - I'll generate a new one for you\n• **Use Existing Keypair** - Select from your existing keypairs\n\nWhat would you prefer?",
                "buttons": [{"text": "Create New Keypair", "value": "create new"}, {"text": "Use Existing Keypair", "value": "existing"}],
                "show_text_input": True
            }
        elif step == "keypair_name_input":
            return {
                "message": "Enter a name for your new keypair (letters, numbers, hyphens only):",
                "show_text_input": True
            }
        
        return {"message": "Please select from the available options or let me know what you'd like to do.", "show_text_input": True}

    async def _handle_parameter_update_enhanced(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Handle parameter updates with smart change detection"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        params = ai_response.get("parameters_detected", {})
        change_type = ai_response.get("change_type", "direct")
        
        # Handle parameter updates with smart confirmation and validation
        updated = self._update_parameters_smart(state, params, change_type, user_email, user_info)
        
        # Check for validation errors first
        if updated.startswith("validation_error:"):
            error_msg = updated.replace("validation_error: ", "")
            return {
                "message": f"❌ {error_msg}",
                "show_text_input": True
            }
        
        # Check if confirmation is needed
        if updated.startswith("pending_confirmation_"):
            field = updated.replace("pending_confirmation_", "")
            pending = self.confirmation_manager.get_pending_confirmation(user_email)
            return {
                "message": f"I see you want to change {field.replace('_', ' ')} from {pending['old_value']} to {pending['new_value']}. Should I update this?",
                "show_text_input": True
            }
        
        # Check completion and suggest next steps - use fresh missing list
        fresh_missing = self._get_missing(cfg)
        logger.info(f"Fresh missing check: {fresh_missing}, environment: {cfg.get('environment')}")
        
        if not fresh_missing and cfg.get("environment"):
            return {"message": f"Excellent! {updated}. Ready to configure networking?", "show_text_input": True}
        elif not fresh_missing and not cfg.get("environment"):
            return await self._suggest_environment_smart(user_email, user_info, f"Perfect! I've got {updated}." if updated else "")
        elif fresh_missing:
            missing_str = ", ".join(fresh_missing)
            if "instance_type" in fresh_missing:
                return {"message": f"Great! {updated}. What instance type would you like? I'd recommend t3.micro for light workloads or t3.small for more demanding tasks.", "show_text_input": True}
            elif "storage_size" in fresh_missing:
                return {"message": f"Nice! {updated}. How much storage do you need? 20GB is usually good for development work.", "show_text_input": True}
            elif "region" in fresh_missing:
                return {"message": f"Perfect! {updated}. Which region would you prefer? US-East-1 is our default and most cost-effective.", "show_text_input": True}
            else:
                return {"message": f"Great! {updated}. Still need: {missing_str}.", "show_text_input": True}
        
        return {"message": "What would you like to configure?", "show_text_input": True}

    async def _handle_pending_confirmation(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Handle pending confirmation responses"""
        confirmation_response = ai_response.get("confirmation_response")
        params = ai_response.get("parameters_detected", {})
        
        # Detect confirmation from message if not detected by AI
        if not confirmation_response:
            user_message = self.conversations[user_email][-1].get("content", "") if self.conversations[user_email] else ""
            confirmation_response = self.confirmation_manager.detect_confirmation_response(user_message)
        
        pending = self.confirmation_manager.get_pending_confirmation(user_email)
        if not pending:
            return {"message": "No pending confirmation found.", "show_text_input": True}
        
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        results = []
        
        if confirmation_response == "positive":
            # Apply the pending change
            cfg[pending["field"]] = pending["new_value"]
            results.append(f"Updated {pending['field'].replace('_', ' ')}: {pending['old_value']} → {pending['new_value']}")
            self.confirmation_manager.process_confirmation(user_email, True)
            
        elif confirmation_response == "negative":
            # Keep original value
            results.append(f"Keeping {pending['field'].replace('_', ' ')} as {pending['old_value']}")
            self.confirmation_manager.process_confirmation(user_email, False)
            
        elif confirmation_response == "conditional":
            # User said "no but use X instead" - extract new value
            field = pending["field"]
            if field in params:
                cfg[field] = params[field]
                results.append(f"Updated {field.replace('_', ' ')} to {params[field]} instead")
            else:
                results.append(f"Keeping {pending['field'].replace('_', ' ')} as {pending['old_value']}")
            self.confirmation_manager.process_confirmation(user_email, False)
        
        # Handle any additional parameters in the confirmation response
        if params:
            additional_updates = self._update_parameters_smart(state, params, "direct", user_email, user_info)
            if additional_updates and additional_updates.startswith("validation_error:"):
                error_msg = additional_updates.replace("validation_error: ", "")
                results.append(f"❌ {error_msg}")
            elif additional_updates and not additional_updates.startswith("pending_confirmation_"):
                results.append(additional_updates)
        
        # Handle cost requests during confirmation
        if ai_response.get("cost_request"):
            cost_text = await self._compute_cost_enhanced(cfg, params, user_info)
            if cost_text:
                results.append(cost_text)
        
        response_text = ". ".join(results) if results else "Confirmation processed"
        
        # Check completion status
        missing = self._get_missing(cfg)
        if not missing and not cfg.get("environment"):
            return await self._suggest_environment_smart(user_email, user_info, response_text)
        elif not missing and cfg.get("environment"):
            return {"message": f"{response_text}. Ready to configure networking?", "show_text_input": True}
        elif missing:
            missing_str = ", ".join(missing)
            return {"message": f"{response_text}. Still need: {missing_str}.", "show_text_input": True}
        
        return {"message": response_text, "show_text_input": True}

    def _update_parameters_smart(self, state: Dict, params: Dict, change_type: str, user_email: str = None, user_info: Dict = None) -> str:
        """Smart parameter update with change tracking, confirmation, and permission validation"""
        cfg = state["collected_parameters"]
        changes = []
        validation_errors = []
        
        for key, value in params.items():
            if value and key in ["environment", "instance_type", "operating_system", "storage_size", "region"]:
                old_value = cfg.get(key)
                
                # VALIDATE PERMISSIONS BEFORE UPDATING
                if user_info and key in ["instance_type", "region", "storage_size"]:
                    current_env = cfg.get("environment") or params.get("environment")
                    if current_env:
                        department = user_info.get("department", "")
                        limits = get_department_limits("aws", current_env, department)
                        
                        # Validate instance type
                        if key == "instance_type":
                            allowed_instances = limits.get("allowed_instance_types", [])
                            if allowed_instances and value not in allowed_instances:
                                validation_errors.append(f"{value} is not allowed in {current_env.upper()} for {department} department. Allowed: {', '.join(allowed_instances)}")
                                continue
                        
                        # Validate region
                        elif key == "region":
                            allowed_regions = limits.get("allowed_regions", [])
                            if allowed_regions and value not in allowed_regions:
                                validation_errors.append(f"{value} region is not allowed in {current_env.upper()} for {department} department. Allowed: {', '.join(allowed_regions)}")
                                continue
                        
                        # Validate storage size
                        elif key == "storage_size":
                            max_storage = limits.get("max_storage_gb")
                            if isinstance(max_storage, int) and isinstance(value, int) and value > max_storage:
                                validation_errors.append(f"{value}GB storage exceeds the {max_storage}GB limit for {current_env.upper()} environment")
                                continue
                
                # Check if this is a change to existing value that needs confirmation
                if old_value and old_value != value and change_type == "ambiguous" and user_email:
                    # Add pending confirmation instead of direct update
                    self.confirmation_manager.add_pending_change(
                        user_email, key, old_value, value
                    )
                    return f"pending_confirmation_{key}"
                
                # Update the parameter if validation passed
                cfg[key] = value
                
                if old_value and old_value != value:
                    if key == "environment":
                        changes.append(f"switched to {value.upper()} environment")
                    elif key == "instance_type":
                        changes.append(f"changed instance to {value}")
                    elif key == "operating_system":
                        changes.append(f"switched to {value}")
                    elif key == "storage_size":
                        changes.append(f"set storage to {value}GB")
                    elif key == "region":
                        changes.append(f"selected {value} region")
                elif not old_value:
                    if key == "environment":
                        changes.append(f"{value.upper()} environment selected")
                    elif key == "instance_type":
                        changes.append(f"{value} instance type")
                    elif key == "operating_system":
                        changes.append(f"{value} operating system")
                    elif key == "storage_size":
                        changes.append(f"{value}GB storage")
                    elif key == "region":
                        changes.append(f"{value} region")
        
        # Update missing parameters after changes
        state["missing_parameters"] = self._get_missing(cfg)
        
        # Log the update for debugging
        logger.info(f"Parameter update: {changes}, validation errors: {validation_errors}, missing now: {state['missing_parameters']}")
        
        # Return validation errors if any
        if validation_errors:
            return f"validation_error: {'; '.join(validation_errors)}"
        
        return ", ".join(changes)

    async def _suggest_environment_smart(self, user_email: str, user_info: Dict, prefix: str = "") -> Dict[str, Any]:
        """Smart environment suggestion based on user access and parameters"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        
        usable_envs = [e for e in ENV_ORDER if check_environment_access(user_info, e)]
        compatible_envs = [e for e in usable_envs if self._is_allowed_in_env(user_info, e, cfg)]
        
        spec_parts = []
        if cfg.get("instance_type"): spec_parts.append(cfg["instance_type"])
        if cfg.get("operating_system"): spec_parts.append(cfg["operating_system"])
        if cfg.get("storage_size"): spec_parts.append(f"{cfg['storage_size']}GB")
        if cfg.get("region"): spec_parts.append(cfg["region"])
        spec_summary = " ".join(spec_parts)
        
        prefix_msg = f"{prefix} " if prefix else ""
        
        # Check if user specified t3.micro or t2.small for prod (not allowed)
        instance_type = cfg.get("instance_type")
        if instance_type in ["t3.micro", "t2.small"] and "prod" in [e for e in ENV_ORDER if self._is_allowed_in_env(user_info, e, cfg)]:
            department = user_info.get("department", "")
            prod_limits = get_department_limits("aws", "prod", department)
            allowed_prod_instances = prod_limits.get("allowed_instance_types", [])
            
            if allowed_prod_instances:
                return {
                    "message": f"{prefix_msg}I see you want {instance_type}, but for PROD environment, your department can use: {', '.join(allowed_prod_instances)}. Would you like to use one of these instead, or stick with DEV environment?",
                    "buttons": [{"text": f"Use {allowed_prod_instances[0]} in PROD", "value": f"{allowed_prod_instances[0]} prod"}, {"text": "Keep DEV", "value": "dev"}],
                    "show_text_input": True
                }
        
        if len(compatible_envs) == 1:
            env = compatible_envs[0]
            if env == "dev":
                msg = f"{prefix_msg}Perfect! I've got your {spec_summary} spec. This looks great for development work - DEV environment will be ideal for testing and building. Ready to set it up?"
            else:
                msg = f"{prefix_msg}Excellent! Your {spec_summary} configuration works perfectly in {env.upper()} environment. Ready to proceed?"
            return {"message": msg, "show_text_input": True}
        
        elif len(compatible_envs) > 1:
            env_list = ", ".join([e.upper() for e in compatible_envs])
            return {
                "message": f"{prefix_msg}Nice! I've configured your {spec_summary} setup. This works perfectly in {env_list} environments. Which environment fits your project best?",
                "show_text_input": True
            }
        
        else:
            # No compatible environments - suggest approval or modification
            for e in ENV_ORDER:
                if e not in usable_envs:
                    # Check if this environment would work with current spec
                    if self._is_allowed_in_env(user_info, e, cfg):
                        return {
                            "message": f"{prefix_msg}I love the {spec_summary} configuration! This needs {e.upper()} environment access. No worries - I can request approval from your manager. It usually takes just a few minutes.",
                            "buttons": [{"text": f"Request {e.upper()} Access", "value": f"request {e}"}, {"text": "Modify Spec", "value": "modify spec"}],
                            "show_text_input": True
                        }
                    elif e == "prod" and instance_type in ["t3.micro", "t2.small"]:
                        # Suggest prod-compatible instances
                        department = user_info.get("department", "")
                        prod_limits = get_department_limits("aws", "prod", department)
                        allowed_prod_instances = prod_limits.get("allowed_instance_types", [])
                        
                        if allowed_prod_instances:
                            return {
                                "message": f"{prefix_msg}For PROD environment, {instance_type} isn't available. Your department can use: {', '.join(allowed_prod_instances)}. Should I request PROD access with a compatible instance?",
                                "buttons": [{"text": f"Request PROD with {allowed_prod_instances[0]}", "value": f"request prod {allowed_prod_instances[0]}"}, {"text": "Use DEV Instead", "value": "dev"}],
                                "show_text_input": True
                            }
            
            return {"message": f"{prefix_msg}Your {spec_summary} spec doesn't fit any accessible environment. Please modify your requirements.", "show_text_input": True}

    async def _handle_cost_estimation_enhanced(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Enhanced cost estimation handling"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        params = ai_response.get("parameters_detected", {})
        
        cost_text = await self._compute_cost_enhanced(cfg, params, user_info)
        
        # If we're in networking phase, maintain the flow
        if self.user_context[user_email]["step"] == "networking_choice":
            return {
                "message": f"{cost_text}\n\nWe're configuring networking - default VPC or existing VPC?",
                "show_text_input": True
            }
        
        return {"message": cost_text or "Cost service unavailable right now. Try again in a moment?", "show_text_input": True}

    async def _compute_cost_enhanced(self, cfg: Dict, params: Dict, user_info: Dict) -> Optional[str]:
        """Enhanced cost computation with MCP service"""
        # Build cost config from current state + new params
        cost_cfg = dict(cfg)
        cost_cfg.update(params)
        
        # Use defaults for missing values
        cost_cfg["environment"] = cost_cfg.get("environment") or ("dev" if check_environment_access(user_info, "dev") else "qa")
        cost_cfg["instance_type"] = cost_cfg.get("instance_type") or "t3.micro"
        cost_cfg["operating_system"] = cost_cfg.get("operating_system") or "ubuntu"
        cost_cfg["storage_size"] = cost_cfg.get("storage_size") or 20
        cost_cfg["region"] = cost_cfg.get("region") or "us-east-1"
        
        cost_result = await self._compute_cost(cost_cfg, "overall")
        if cost_result:
            spec_parts = []
            if cost_cfg.get('instance_type'): spec_parts.append(cost_cfg['instance_type'])
            if cost_cfg.get('operating_system'): spec_parts.append(cost_cfg['operating_system'])
            if cost_cfg.get('storage_size'): spec_parts.append(f"{cost_cfg['storage_size']}GB")
            if cost_cfg.get('region'): spec_parts.append(f"in {cost_cfg['region']}")
            spec_info = " ".join(spec_parts)
            return f"{cost_result} for {spec_info}"
        
        return "Cost service unavailable"

    async def _handle_environment_request(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Handle environment access requests and approval workflow"""
        params = ai_response.get("parameters_detected", {})
        actions = ai_response.get("actions", [])
        env = params.get("environment")
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        
        # Handle direct approval sending
        if "send_approval" in actions or any(phrase in ai_response.get("response", "").lower() for phrase in ["send approval", "send request"]):
            if env:
                return await self._send_environment_approval_request(user_email, user_info, env)
            else:
                return {
                    "message": "Which environment approval should I send? (dev/qa/prod)",
                    "show_text_input": True
                }
        
        if not env:
            return {
                "message": "Which environment access do you need? (dev/qa/prod)",
                "show_text_input": True
            }
        
        # Check if user already has access to this environment
        has_access = check_environment_access(user_info, env)
        
        if has_access:
            # User has access, but check if current spec is allowed in this environment
            if cfg and not self._is_allowed_in_env(user_info, env, cfg):
                # User has access but spec not allowed - suggest alternatives
                department = user_info.get("department", "")
                limits = get_department_limits("aws", env, department)
                allowed_instances = limits.get("allowed_instance_types", [])
                
                current_instance = cfg.get("instance_type")
                if current_instance and allowed_instances:
                    return {
                        "message": f"You have {env.upper()} access, but {current_instance} isn't allowed. In {env.upper()}, you can use: {', '.join(allowed_instances)}. Want to switch to one of these?",
                        "buttons": [{"text": f"Use {allowed_instances[0]}", "value": f"{allowed_instances[0]} {env}"}, {"text": "Keep Current Spec", "value": "keep spec"}],
                        "show_text_input": True
                    }
                else:
                    return {
                        "message": f"You have {env.upper()} access, but your current configuration isn't allowed in {env.upper()}. Please check the allowed values for your department.",
                        "show_text_input": True
                    }
            else:
                return {
                    "message": f"Perfect! You already have {env.upper()} environment access. Ready to create an instance?",
                    "show_text_input": True
                }
        
        # User doesn't have access - check if spec would be allowed if they had access
        if cfg and self._is_allowed_in_env(user_info, env, cfg):
            # Spec would work in this environment, offer approval
            department = user_info.get("department", "")
            limits = get_department_limits("aws", env, department)
            allowed_instances = limits.get("allowed_instance_types", [])
            
            if env == "prod" and allowed_instances:
                instance_list = ", ".join(allowed_instances)
                return {
                    "message": f"Your configuration would work in PROD! In PROD environment, you'll have access to: {instance_list} instances. Should I request approval from your manager?",
                    "buttons": [{"text": "Send Request", "value": f"request {env}"}, {"text": "Not Now", "value": "cancel"}],
                    "show_text_input": True
                }
            else:
                return {
                    "message": f"Your configuration is perfect for {env.upper()}! Should I request {env.upper()} access from your manager?",
                    "buttons": [{"text": "Send Request", "value": f"request {env}"}, {"text": "Not Now", "value": "cancel"}],
                    "show_text_input": True
                }
        else:
            # Spec wouldn't work even with access - suggest alternatives
            usable_envs = [e for e in ENV_ORDER if check_environment_access(user_info, e)]
            compatible_envs = [e for e in usable_envs if self._is_allowed_in_env(user_info, e, cfg)]
            
            if compatible_envs:
                env_list = ", ".join([e.upper() for e in compatible_envs])
                return {
                    "message": f"You don't have {env.upper()} access, but your configuration works perfectly in {env_list}. Want to use one of these instead, or modify your spec for {env.upper()}?",
                    "buttons": [{"text": f"Use {compatible_envs[0].upper()}", "value": f"launch_{compatible_envs[0]}"}, {"text": f"Request {env.upper()}", "value": f"request {env}"}],
                    "show_text_input": True
                }
            else:
                return {
                    "message": f"I can request {env.upper()} access from your manager, but you'll need to adjust your configuration to match {env.upper()} requirements. Should I send the request anyway?",
                    "buttons": [{"text": "Send Request", "value": f"request {env}"}, {"text": "Check Requirements", "value": f"allowed values {env}"}],
                    "show_text_input": True
                }

    async def _handle_networking_start(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        """Start networking configuration phase"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        
        # Check if all required parameters are present
        missing = self._get_missing(cfg)
        if missing:
            missing_str = ", ".join(missing)
            return {
                "message": f"Let's finish the basic configuration first. Still need: {missing_str}. What would you like to specify?",
                "show_text_input": True
            }
        
        if not cfg.get("environment"):
            return await self._suggest_environment_smart(user_email, user_info, "Almost ready for networking!")
        
        # Initialize networking context
        self.user_context[user_email]["step"] = "networking_choice"
        self.user_context[user_email]["config"] = {
            "vpc_mode": None, "selected_vpc_id": None,
            "subnet_mode": None, "selected_subnet_id": None, "subnet_type": None,
            "sg_mode": None, "selected_sg_id": None,
            "key_pair": {"type": None, "name": None}
        }
        
        # Show current configuration summary
        spec_summary = f"{cfg.get('instance_type')} {cfg.get('operating_system')} {cfg.get('storage_size')}GB in {cfg.get('region')} ({cfg.get('environment', '').upper()})"
        
        # Check if user already specified networking preference
        networking_pref = self.user_context[user_email].get("networking_preference")
        
        if networking_pref == "default":
            return await self._handle_default_vpc_flow(user_email, user_info)
        elif networking_pref == "existing":
            return await self._handle_existing_vpc_flow(user_email, user_info)
        else:
            return {
                "message": f"Perfect! Your {spec_summary} instance is ready for networking setup.\n\nI can use AWS default settings for quick deployment, or you can choose existing VPC for custom networking. What would you prefer?",
                "buttons": [{"text": "Use Default", "value": "default vpc"}, {"text": "Use Existing", "value": "existing vpc"}],
                "show_text_input": True
            }

    async def _handle_deploy_intent(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        """Handle deploy intent - start deployment process"""
        step = self.user_context[user_email]["step"]
        
        if step == "security_approval":
            return await self._show_final_approval(user_email, user_info)
        elif step in ["networking_choice", "vpc_selection", "subnet_selection", "sg_selection", "keypair_selection"]:
            return {"message": "We're almost there! Let's just finish setting up the networking first.", "show_text_input": True}
        else:
            # Check if all parameters are ready
            state = self.conversation_states[user_email]
            missing = self._get_missing(state["collected_parameters"])
            if missing:
                missing_str = ", ".join(missing)
                return {"message": f"Almost there! Still need: {missing_str} before we can deploy.", "show_text_input": True}
            elif not state["collected_parameters"].get("environment"):
                return await self._suggest_environment_smart(user_email, user_info, "Ready to deploy!")
            else:
                return await self._handle_networking_start(user_email, user_info)

    async def _handle_allowed_values_query(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Handle queries about allowed values for departments and environments"""
        params = ai_response.get("parameters_detected", {})
        env = params.get("environment")
        user_department = user_info.get("department", "")
        
        # Check if user is asking about a different department
        original_msg = self.conversations.get(user_email, [])[-1].get("content", "").lower() if self.conversations.get(user_email) else ""
        
        # Detect if user is asking about different department values
        other_departments = ["datascience", "devops", "engineering", "finance", "marketing", "hr"]
        asked_department = None
        for dept in other_departments:
            if dept in original_msg and dept.lower() != user_department.lower():
                asked_department = dept
                break
        
        # If user is asking about different department, show restriction message
        if asked_department:
            return {
                "message": f"🔒 You are restricted to see other department allowed values. You can only view allowed values for your own department ({user_department}).",
                "show_text_input": True
            }
        
        # If no specific environment mentioned, show all accessible environments
        if not env:
            accessible_envs = [e for e in ENV_ORDER if check_environment_access(user_info, e)]
            if not accessible_envs:
                return {
                    "message": "You don't have access to any environments yet. Would you like me to request access?",
                    "buttons": [{"text": "Request DEV Access", "value": "request dev"}, {"text": "Request QA Access", "value": "request qa"}, {"text": "Request PROD Access", "value": "request prod"}],
                    "show_text_input": True
                }
            
            # Show allowed values for all accessible environments
            env_info = []
            for e in accessible_envs:
                limits = get_department_limits("aws", e, user_department)
                instances = ", ".join(limits.get("allowed_instance_types", [])) or "None"
                regions = ", ".join(limits.get("allowed_regions", [])) or "None"
                max_storage = limits.get("max_storage_gb", "No limit")
                env_info.append(f"{e.upper()}: Instances: {instances} | Regions: {regions} | Max Storage: {max_storage}GB")
            
            return {
                "message": f"Allowed values for {user_department} department:\n\n" + "\n\n".join(env_info),
                "show_text_input": True
            }
        
        # Show specific environment details for user's own department
        limits = get_department_limits("aws", env, user_department)
        allowed_instances = limits.get("allowed_instance_types", [])
        allowed_regions = limits.get("allowed_regions", [])
        max_storage = limits.get("max_storage_gb")
        requires_approval = limits.get("requires_approval", True)
        
        # Check if user has access to this environment
        has_access = check_environment_access(user_info, env)
        access_status = "✅ You have access" if has_access else "❌ Requires approval"
        
        instances_str = ", ".join(allowed_instances) if allowed_instances else "None available"
        regions_str = ", ".join(allowed_regions) if allowed_regions else "None available"
        storage_str = f"{max_storage}GB" if isinstance(max_storage, int) else "No limit"
        
        # Check what user specifically asked for
        if "instance" in original_msg and "region" not in original_msg and "storage" not in original_msg:
            message = f"**Allowed instances in {env.upper()} for {user_department}:**\n{instances_str}"
        elif "region" in original_msg and "instance" not in original_msg and "storage" not in original_msg:
            message = f"**Allowed regions in {env.upper()} for {user_department}:**\n{regions_str}"
        elif "storage" in original_msg and "instance" not in original_msg and "region" not in original_msg:
            message = f"**Max storage in {env.upper()} for {user_department}:**\n{storage_str}"
        else:
            message = f"""**{env.upper()} Environment - {user_department} Department**

{access_status}

**Allowed Instance Types:**
{instances_str}

**Allowed Regions:**
{regions_str}

**Max Storage:**
{storage_str}

**Requires Approval:**
{'Yes' if requires_approval else 'No'}"""
        
        buttons = []
        if not has_access and requires_approval:
            buttons.append({"text": f"Request {env.upper()} Access", "value": f"request {env}"})
        
        return {
            "message": message,
            "buttons": buttons,
            "show_text_input": True
        }

    async def _handle_multi_intent_enhanced(self, user_email: str, user_info: Dict, ai_response: Dict) -> Dict[str, Any]:
        """Handle multi-intent requests with enhanced processing"""
        state = self.conversation_states[user_email]
        cfg = state["collected_parameters"]
        params = ai_response.get("parameters_detected", {})
        actions = ai_response.get("actions", [])
        results = []
        
        # Handle parameter updates first
        if "parameter_update" in actions and params:
            change_type = ai_response.get("parameters_detected", {}).get("change_type", "direct")
            updated = self._update_parameters_smart(state, params, change_type, user_email, user_info)
            if updated and updated.startswith("validation_error:"):
                # Return validation error immediately
                error_msg = updated.replace("validation_error: ", "")
                return {
                    "message": f"❌ {error_msg}",
                    "show_text_input": True
                }
            elif updated and not updated.startswith("pending_confirmation_"):
                results.append(f"Updated {updated}")
            elif updated.startswith("pending_confirmation_"):
                # Return confirmation request immediately for ambiguous changes
                field = updated.replace("pending_confirmation_", "")
                pending = self.confirmation_manager.get_pending_confirmation(user_email)
                return {
                    "message": f"I see you want to change {field.replace('_', ' ')} from {pending['old_value']} to {pending['new_value']}. Should I update this?",
                    "show_text_input": True
                }
        
        # Handle EC2 creation parameters
        if params:
            updated = self._update_parameters_smart(state, params, "direct", user_email, user_info)
            if updated and updated.startswith("validation_error:"):
                # Return validation error immediately
                error_msg = updated.replace("validation_error: ", "")
                return {
                    "message": f"❌ {error_msg}",
                    "show_text_input": True
                }
            elif updated:
                results.append(f"Got {updated}")
        
        # Handle environment approval requests - PRIORITY HANDLING
        original_msg = ai_response.get("response", "").lower()
        user_message = self.conversations.get(user_email, [])[-1].get("content", "").lower() if self.conversations.get(user_email) else ""
        
        # Check for prod approval request in original message
        if any(phrase in user_message for phrase in ["request approval for prod", "approval for prod", "prod approval", "request prod"]):
            # Send prod approval request
            try:
                approval_result = await self._send_environment_approval_request(user_email, user_info, "prod")
                results.append("PROD access request sent to your manager")
            except Exception as e:
                logger.error(f"Failed to send prod approval: {e}")
                results.append("I can request PROD access from your manager")
        
        # Handle other environment requests
        if "approval_request" in actions or "environment_request" in actions:
            env = params.get("environment")
            if env and env != "prod":  # prod already handled above
                if "send_approval" in actions:
                    return await self._send_environment_approval_request(user_email, user_info, env)
                else:
                    # Check access and suggest accordingly
                    has_access = check_environment_access(user_info, env)
                    if not has_access:
                        results.append(f"I can request {env.upper()} access from your manager")
                    else:
                        results.append(f"You already have {env.upper()} access")
        
        # Handle cost estimation
        if "cost_estimation" in actions or ai_response.get("cost_request"):
            cost_text = await self._compute_cost_enhanced(cfg, params, user_info)
            if cost_text:
                results.append(cost_text)
            else:
                results.append("Cost service unavailable right now")
        
        # Handle allowed values queries
        if "allowed_values_query" in actions:
            env = params.get("environment")
            if env:
                department = user_info.get("department", "")
                limits = get_department_limits("aws", env, department)
                allowed_instances = ", ".join(limits.get("allowed_instance_types", [])) or "None"
                results.append(f"In {env.upper()}: {allowed_instances}")
        
        # Handle unrelated service mentions
        service = ai_response.get("service_mentioned", "").lower()
        if service in ["s3", "rds", "lambda", "dynamodb", "sns", "sqs"]:
            results.append(f"I specialize in EC2 instances - for {service.upper()} you'd need AWS console or other tools")
        elif service in ["gcp", "azure"]:
            results.append(f"I'm focused on AWS - for {service.upper()} you'd need their respective platforms")
        
        # Handle networking requests
        if "networking_config" in actions:
            # Check if ready for networking
            missing = self._get_missing(cfg)
            if not missing and cfg.get("environment"):
                return await self._handle_networking_start(user_email, user_info)
            else:
                results.append("Let's finish the basic configuration first before networking")
        
        response_text = ". ".join(results) if results else ai_response.get("response", "")
        
        # Check if ready for next step after processing all intents - use fresh missing
        fresh_missing = self._get_missing(cfg)
        if not fresh_missing and cfg.get("environment") and "networking_config" not in actions:
            return {"message": f"{response_text}. Ready to configure networking?", "show_text_input": True}
        elif not fresh_missing and not cfg.get("environment"):
            return await self._suggest_environment_smart(user_email, user_info, response_text)
        elif fresh_missing:
            missing_str = ", ".join(fresh_missing)
            return {"message": f"{response_text}. Still need: {missing_str}.", "show_text_input": True}
        
        return {"message": response_text, "show_text_input": True}

    # -------------------- NETWORKING FLOW METHODS --------------------

    async def _handle_default_vpc_flow(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        """Handle default VPC flow with keypair selection"""
        ctx = self.user_context[user_email]
        ctx["config"]["vpc_mode"] = "default"
        ctx["config"]["vpc_id"] = "vpc-default"
        ctx["config"]["subnet_mode"] = "default"
        ctx["config"]["subnet_id"] = "subnet-default"
        ctx["config"]["subnet_type"] = "public"
        ctx["config"]["sg_mode"] = "default"
        ctx["config"]["sg_id"] = "sg-default"
        
        # Go to keypair selection step
        ctx["step"] = "keypair_selection"
        
        return {
            "message": "Perfect! Using **Default VPC** with **public subnet** and **default security group**.\n\nFor SSH access, do you want to create new keypair or use existing?",
            "buttons": [
                {"text": "Create New Keypair", "value": "create new"},
                {"text": "Use Existing Keypair", "value": "use existing"}
            ],
            "show_text_input": True
        }

    async def _handle_existing_vpc_flow(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        from .aws_fetcher_async import AWSResourceFetcher
        
        cfg = self.conversation_states[user_email]["collected_parameters"]
        region = cfg.get("region", "us-east-1")
        environment = cfg.get("environment", "dev")
        
        # Set VPC mode to existing
        ctx = self.user_context[user_email]
        ctx["config"]["vpc_mode"] = "existing"
        
        try:
            # Fetch real VPCs using AWS fetcher
            fetcher = AWSResourceFetcher(environment, region)
            vpcs = await fetcher.get_vpcs()
            
            if not vpcs:
                # Fallback to default VPC if no VPCs found
                logger.warning(f"No VPCs found in {region}, falling back to default")
                return await self._handle_default_vpc_flow(user_email, user_info)
            
            # Store VPCs and set step
            ctx["step"] = "vpc_selection"
            ctx["available_vpcs"] = vpcs
            
            # Show simple list of VPC IDs only
            buttons = []
            for vpc in vpcs[:10]:  # Show up to 10 VPCs
                buttons.append({"text": vpc['id'], "value": vpc['id']})
            
            return {
                "message": f"**Available VPCs in {region}:**\n\nSelect a VPC:",
                "buttons": buttons,
                "show_text_input": True
            }
        except Exception as e:
            logger.error(f"Error fetching VPCs: {e}")
            # Fallback to default VPC on error
            return await self._handle_default_vpc_flow(user_email, user_info)

    async def _handle_vpc_choice(self, user_email: str, user_info: Dict, vpc_choice: str) -> Dict[str, Any]:
        from .aws_fetcher_async import AWSResourceFetcher
        
        ctx = self.user_context[user_email]
        cfg = self.conversation_states[user_email]["collected_parameters"]
        
        # Handle VPC ID input (either from button or typed)
        vpc_id = vpc_choice.strip()
        if not vpc_id.startswith("vpc-"):
            # Try to find VPC by partial match
            vpcs = ctx.get("available_vpcs", [])
            for vpc in vpcs:
                if vpc["id"] in vpc_choice:
                    vpc_id = vpc["id"]
                    break
        
        try:
            fetcher = AWSResourceFetcher(cfg.get("environment", "dev"), cfg.get("region", "us-east-1"))
            
            # If user entered new VPC ID, fetch its details
            if vpc_id.startswith("vpc-"):
                vpc_details = await fetcher.get_vpc_details(vpc_id)
                if not vpc_details:
                    return {
                        "message": f"VPC '{vpc_id}' not found. Please enter a valid VPC ID:",
                        "show_text_input": True
                    }
                
                selected_vpc = vpc_details
            else:
                return {
                    "message": "Please enter a valid VPC ID (format: vpc-xxxxxxxxx):",
                    "show_text_input": True
                }
            
            # Store VPC configuration and show details
            ctx["config"]["vpc_id"] = selected_vpc["id"]
            ctx["config"]["vpc_cidr"] = selected_vpc["cidr"]
            
            # Fetch subnets for selected VPC
            subnets = await fetcher.get_subnets(selected_vpc["id"])
            
            if not subnets:
                return {
                    "message": f"No subnets found in VPC {selected_vpc['id']}. Please select different VPC:",
                    "show_text_input": True
                }
            
            # Store subnets and advance step
            ctx["available_subnets"] = subnets
            ctx["step"] = "subnet_selection"
            
            # Show simple list of subnet IDs only
            buttons = []
            for subnet in subnets[:10]:
                buttons.append({"text": subnet['id'], "value": subnet['id']})
            
            return {
                "message": f"**VPC Selected:** {selected_vpc['id']} - {selected_vpc['cidr']}\n\n**Available Subnets:**\n\nSelect a subnet:",
                "buttons": buttons,
                "show_text_input": True
            }
            
        except Exception as e:
            logger.error(f"Error handling VPC choice: {e}")
            return {
                "message": "Error processing VPC selection. Please try again:",
                "show_text_input": True
            }

    async def _handle_subnet_choice(self, user_email: str, user_info: Dict, subnet_choice: str) -> Dict[str, Any]:
        from .aws_fetcher_async import AWSResourceFetcher
        
        ctx = self.user_context[user_email]
        cfg = self.conversation_states[user_email]["collected_parameters"]
        
        # Handle subnet ID input
        subnet_id = subnet_choice.strip()
        if not subnet_id.startswith("subnet-"):
            subnets = ctx.get("available_subnets", [])
            for subnet in subnets:
                if subnet["id"] in subnet_choice:
                    subnet_id = subnet["id"]
                    break
        
        try:
            fetcher = AWSResourceFetcher(cfg.get("environment", "dev"), cfg.get("region", "us-east-1"))
            
            # Validate subnet belongs to selected VPC
            vpc_id = ctx["config"].get("vpc_id")
            if subnet_id.startswith("subnet-"):
                subnet_details = await fetcher.get_subnet_details(subnet_id)
                if not subnet_details:
                    return {
                        "message": f"Subnet '{subnet_id}' not found. Please enter valid subnet ID:",
                        "show_text_input": True
                    }
                
                # Check if subnet belongs to selected VPC
                if subnet_details.get("vpc_id") != vpc_id:
                    return {
                        "message": f"Subnet '{subnet_id}' does not belong to VPC {vpc_id}. Please select subnet from this VPC:",
                        "show_text_input": True
                    }
                
                selected_subnet = subnet_details
            else:
                return {
                    "message": "Please enter valid subnet ID (format: subnet-xxxxxxxxx):",
                    "show_text_input": True
                }
            
            # Store subnet configuration and show details
            ctx["config"]["subnet_id"] = selected_subnet["id"]
            ctx["config"]["subnet_type"] = "public" if selected_subnet.get("public", False) else "private"
            ctx["config"]["subnet_cidr"] = selected_subnet.get("cidr", "N/A")
            ctx["config"]["subnet_az"] = selected_subnet.get("availability_zone", "N/A")
            
            # Fetch security groups for the VPC
            security_groups = await fetcher.get_security_groups(vpc_id)
            ctx["available_sgs"] = security_groups
            ctx["step"] = "sg_selection"
            
            # Show simple list of SG IDs
            buttons = [{"text": "Default", "value": "default"}]
            for sg in security_groups[:5]:
                buttons.append({"text": sg['id'], "value": sg['id']})
            
            return {
                "message": f"**Subnet Selected:** {selected_subnet['id']} - {selected_subnet.get('cidr')} ({ctx['config']['subnet_type']}) in {ctx['config']['subnet_az']}\n\n**Available Security Groups:**\n\nSelect security group:",
                "buttons": buttons,
                "show_text_input": True
            }
            
        except Exception as e:
            logger.error(f"Error handling subnet choice: {e}")
            return {
                "message": "Error processing subnet selection. Please try again:",
                "show_text_input": True
            }

    async def _handle_sg_choice(self, user_email: str, user_info: Dict, sg_choice: str) -> Dict[str, Any]:
        from .aws_fetcher_async import AWSResourceFetcher
        
        ctx = self.user_context[user_email]
        cfg = self.conversation_states[user_email]["collected_parameters"]
        
        if "default" in sg_choice.lower():
            ctx["config"]["sg_id"] = "sg-default"
            sg_display = "Default - Inbound: SSH(22), HTTP(80), HTTPS(443) | Outbound: All traffic"
        else:
            # Handle SG ID input
            sg_id = sg_choice.strip()
            if not sg_id.startswith("sg-"):
                sgs = ctx.get("available_sgs", [])
                for sg in sgs:
                    if sg["id"] in sg_choice:
                        sg_id = sg["id"]
                        break
            
            try:
                fetcher = AWSResourceFetcher(cfg.get("environment", "dev"), cfg.get("region", "us-east-1"))
                
                # Validate SG belongs to selected VPC
                vpc_id = ctx["config"].get("vpc_id")
                if sg_id.startswith("sg-"):
                    sg_details = await fetcher.get_security_group_details(sg_id)
                    if not sg_details:
                        return {
                            "message": f"Security Group '{sg_id}' not found. Please enter valid SG ID:",
                            "show_text_input": True
                        }
                    
                    # Check if SG belongs to selected VPC
                    if sg_details.get("vpc_id") != vpc_id:
                        return {
                            "message": f"Security Group '{sg_id}' does not belong to VPC {vpc_id}. Please select SG from this VPC:",
                            "show_text_input": True
                        }
                    
                    ctx["config"]["sg_id"] = sg_details["id"]
                    
                    # Get detailed port information for display
                    sg_rules = await fetcher.get_security_group_rules(sg_details["id"])
                    if sg_rules:
                        # Parse ingress rules to show actual ports
                        ingress_ports = []
                        for rule in sg_rules.get("ingress", []):
                            port = rule.get("port")
                            protocol = rule.get("protocol", "tcp")
                            if port == 22:
                                ingress_ports.append("SSH(22)")
                            elif port == 80:
                                ingress_ports.append("HTTP(80)")
                            elif port == 443:
                                ingress_ports.append("HTTPS(443)")
                            elif port == 3389:
                                ingress_ports.append("RDP(3389)")
                            elif port:
                                ingress_ports.append(f"{protocol.upper()}({port})")
                        
                        ingress_display = ", ".join(ingress_ports) if ingress_ports else "No inbound rules"
                        egress_rules = sg_rules.get("egress", [])
                        egress_display = "All traffic" if egress_rules else "No outbound rules"
                        
                        sg_display = f"{sg_details['id']} - Inbound: {ingress_display} | Outbound: {egress_display}"
                    else:
                        sg_display = f"{sg_details['id']} - Custom security group"
                else:
                    return {
                        "message": "Please enter valid Security Group ID (format: sg-xxxxxxxxx):",
                        "show_text_input": True
                    }
            except Exception as e:
                logger.error(f"Error handling SG choice: {e}")
                return {
                    "message": "Error processing security group selection. Please try again:",
                    "show_text_input": True
                }
        
        # Move to keypair selection
        ctx["step"] = "keypair_selection"
        
        return {
            "message": f"**Security Group Selected:** {sg_display}\n\nFor SSH access, do you want to create new keypair or use existing?",
            "buttons": [
                {"text": "Create New Keypair", "value": "create new"},
                {"text": "Use Existing Keypair", "value": "use existing"}
            ],
            "show_text_input": True
        }

    async def _handle_keypair_choice(self, user_email: str, user_info: Dict, keypair_choice: str) -> Dict[str, Any]:
        ctx = self.user_context[user_email]
        
        if "create new" in keypair_choice.lower():
            ctx["config"]["keypair_type"] = "new"
            ctx["step"] = "keypair_name_input"
            return {
                "message": "What would you like to name your new keypair? (letters, numbers, hyphens only):",
                "show_text_input": True
            }
        elif any(word in keypair_choice.lower() for word in ["existing", "use existing", "existing keypair"]):
            # User wants existing keypair - show available keypairs
            try:
                from .aws_fetcher_async import AWSResourceFetcher
                cfg = self.conversation_states[user_email]["collected_parameters"]
                region = cfg.get("region", "us-east-1")
                environment = cfg.get("environment", "dev")
                
                fetcher = AWSResourceFetcher(environment, region)
                keypairs = await fetcher.get_keypairs()
                ctx["available_keypairs"] = keypairs
                
                if not keypairs:
                    return {
                        "message": f"No existing keypairs found in {region}. Would you like to create a new one?",
                        "buttons": [{"text": "Create New Keypair", "value": "create new"}],
                        "show_text_input": True
                    }
                
                # Show simple list of all keypairs
                buttons = []
                for kp in keypairs:
                    buttons.append({"text": f"Use {kp['name']}", "value": kp['name']})
                
                return {
                    "message": f"Available keypairs in {region}:\n\nSelect an existing keypair:",
                    "buttons": buttons,
                    "show_text_input": True
                }
                
            except Exception as e:
                logger.error(f"Error fetching keypairs: {e}")
                return {
                    "message": "Error fetching keypairs. Would you like to create a new one?",
                    "buttons": [{"text": "Create New Keypair", "value": "create new"}],
                    "show_text_input": True
                }
        else:
            # Specific keypair selected by name
            keypair_name = keypair_choice.strip()
            
            # Check if keypair exists
            try:
                from .aws_fetcher_async import AWSResourceFetcher
                cfg = self.conversation_states[user_email]["collected_parameters"]
                region = cfg.get("region", "us-east-1")
                environment = cfg.get("environment", "dev")
                
                fetcher = AWSResourceFetcher(environment, region)
                keypair_exists = await fetcher.check_keypair_exists(keypair_name)
                
                if keypair_exists:
                    ctx["config"]["keypair_type"] = "existing"
                    ctx["config"]["keypair_name"] = keypair_name
                    
                    # Move to security approval
                    self.user_context[user_email]["step"] = "security_approval"
                    return await self._show_security_approval(user_email, user_info)
                else:
                    return {
                        "message": f"Keypair '{keypair_name}' not found in {region}. Please enter a valid keypair name or create new:",
                        "buttons": [{"text": "Create New Keypair", "value": "create new"}],
                        "show_text_input": True
                    }
                    
            except Exception as e:
                logger.error(f"Error checking keypair: {e}")
                return {
                    "message": "Error checking keypair. Please try again:",
                    "show_text_input": True
                }

    async def _handle_keypair_name_input(self, user_email: str, user_info: Dict, keypair_name: str) -> Dict[str, Any]:
        """Handle keypair name input with validation"""
        if not keypair_name or not keypair_name.strip():
            return {"message": "Please enter a valid keypair name:", "show_text_input": True}
        
        keypair_name = keypair_name.strip()
        
        # Validate keypair name format
        import re
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', keypair_name):
            return {
                "message": "Keypair name must start with a letter or number and contain only letters, numbers, hyphens, and underscores. Please try again:",
                "show_text_input": True
            }
        
        # Check if keypair exists in AWS
        try:
            from .aws_fetcher_async import AWSResourceFetcher
            cfg = self.conversation_states[user_email]["collected_parameters"]
            region = cfg.get("region", "us-east-1")
            environment = cfg.get("environment", "dev")
            
            fetcher = AWSResourceFetcher(environment, region)
            keypair_exists = await fetcher.check_keypair_exists(keypair_name)
            
            if keypair_exists:
                return {
                    "message": f"Keypair '{keypair_name}' already exists in {region}. Choose an option:",
                    "buttons": [
                        {"text": f"Use Existing '{keypair_name}'", "value": f"existing:{keypair_name}"},
                        {"text": "Enter Different Name", "value": "create new"}
                    ],
                    "show_text_input": True
                }
            
            # Keypair name is available - store and proceed
            ctx = self.user_context[user_email]
            ctx["config"]["keypair_type"] = "new"
            ctx["config"]["keypair_name"] = keypair_name
            ctx["step"] = "security_approval"
            
            return await self._show_security_approval(user_email, user_info)
            
        except Exception as e:
            logger.error(f"Error checking keypair '{keypair_name}' in {region}: {e}")
            # Continue with the name if check fails
            ctx = self.user_context[user_email]
            ctx["config"]["keypair_type"] = "new"
            ctx["config"]["keypair_name"] = keypair_name
            ctx["step"] = "security_approval"
            
            return await self._show_security_approval(user_email, user_info)

    async def _show_security_approval(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        """Show security group configuration for approval"""
        cfg = self.conversation_states[user_email]["collected_parameters"]
        ctx = self.user_context[user_email]["config"]
        
        # Show essential networking parameters only
        vpc_id = ctx.get('vpc_id', 'default')
        subnet_id = ctx.get('subnet_id', 'default') 
        subnet_type = ctx.get('subnet_type', 'public')
        sg_id = ctx.get('sg_id', 'default')
        keypair_name = ctx.get('keypair_name', 'auto-generated')
        
        # Show clear VPC/Subnet mode in security approval
        vpc_display = "Default VPC" if vpc_id == "vpc-default" else vpc_id
        subnet_display = "Default Subnet" if subnet_id == "subnet-default" else subnet_id
        sg_display = "Default SG" if sg_id == "sg-default" else sg_id
        
        summary = f"""**Configuration Ready**

**Instance:** {cfg.get('instance_type')} {cfg.get('operating_system')} {cfg.get('storage_size')}GB
**Environment:** {cfg.get('environment', '').upper()}

**Network:**
• VPC: {vpc_display}
• Subnet: {subnet_display} ({subnet_type})
• Security Group: {sg_display}
• Keypair: {keypair_name}

**Approve configuration?**"""
        
        return {
            "message": summary,
            "buttons": [{"text": "Approve", "value": "approve"}, {"text": "Cancel", "value": "cancel"}],
            "show_text_input": True
        }

    async def _show_final_approval(self, user_email: str, user_info: Dict) -> Dict[str, Any]:
        """Show simplified deployment configuration for final approval"""
        cfg = self.conversation_states[user_email]["collected_parameters"]
        ctx = self.user_context[user_email]["config"]
        
        # Simplified networking details - only essential parameters
        vpc_id = ctx.get('vpc_id', 'default')
        subnet_id = ctx.get('subnet_id', 'default')
        subnet_type = ctx.get('subnet_type', 'public')
        sg_id = ctx.get('sg_id', 'default')
        keypair_name = ctx.get('keypair_name', 'auto-generated')
        
        # Clear keypair status
        if ctx.get('keypair_type') == 'new':
            keypair_status = "Create New"
        else:
            keypair_status = "Use Existing"
        
        # Show VPC/Subnet mode clearly
        vpc_display = "Default VPC" if vpc_id == "vpc-default" else vpc_id
        subnet_display = "Default Subnet" if subnet_id == "subnet-default" else subnet_id
        sg_display = "Default SG" if sg_id == "sg-default" else sg_id
        
        summary = f"""🚀 **Ready to Deploy**

**Instance:** {cfg.get('instance_type')} {cfg.get('operating_system')} {cfg.get('storage_size')}GB
**Environment:** {cfg.get('environment', '').upper()}
**Region:** {cfg.get('region')}

**Network Settings:**
• VPC: {vpc_display}
• Subnet: {subnet_display} ({subnet_type})
• Security Group: {sg_display}
• Keypair: {keypair_name} ({keypair_status})

**Deploy now?**"""
        
        self.user_context[user_email]["step"] = "final_deploy"
        return {
            "message": summary,
            "buttons": [{"text": "Deploy Now", "value": "deploy"}, {"text": "Cancel", "value": "cancel"}],
            "show_text_input": True
        }

    async def _execute_deployment(self, user_email: str, user_info: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Get the collected parameters and networking config
            state = self.conversation_states[user_email]
            cfg = state["collected_parameters"]
            ctx = self.user_context[user_email]["config"]
            
            # Generate unique request identifier
            import uuid
            import time
            import json
            request_id = f"{user_info.get('department', 'user').lower()}_aws_{cfg.get('environment', 'dev')}_{uuid.uuid4().hex[:8]}"
            
            # Build parameters for infrastructure request
            parameters = {
                "department": user_info.get("department", "Unknown"),
                "created_by": user_info.get("email", user_email),
                "environment": cfg.get("environment", "dev"),
                "instance_type": cfg.get("instance_type", "t3.micro"),
                "storage_size": cfg.get("storage_size", 8),
                "region": cfg.get("region", "us-east-1"),
                "operating_system": cfg.get("operating_system", "ubuntu"),
            }
            
            # Add keypair configuration - THIS IS THE KEY FIX
            keypair_type = ctx.get("keypair_type", "auto")
            keypair_name = ctx.get("keypair_name", self._generate_keypair_name(user_info))
            
            # Set keypair parameters correctly
            parameters["key_name"] = keypair_name
            if keypair_type == "new":
                parameters["create_new_keypair"] = True
                logger.info(f"DEPLOYMENT: Creating NEW keypair: {keypair_name}")
            else:
                parameters["create_new_keypair"] = False
                logger.info(f"DEPLOYMENT: Using EXISTING keypair: {keypair_name}")
            
            # Add networking configuration - Terraform Manager format
            if ctx.get("vpc_mode") == "existing" and ctx.get("vpc_id") and ctx.get("vpc_id") != "vpc-default":
                parameters["vpc"] = {
                    "mode": "existing",
                    "id": ctx.get("vpc_id")
                }
            
            if ctx.get("subnet_mode") == "existing" and ctx.get("subnet_id") and ctx.get("subnet_id") != "subnet-default":
                parameters["subnet"] = {
                    "mode": "existing",
                    "id": ctx.get("subnet_id"),
                    "type": ctx.get("subnet_type", "public")
                }
            else:
                # For default subnet, only send type for associate_public_ip calculation
                parameters["subnet"] = {
                    "type": ctx.get("subnet_type", "public")
                }
            
            if ctx.get("sg_mode") == "existing" and ctx.get("sg_id") and ctx.get("sg_id") != "sg-default":
                parameters["security_group"] = {
                    "mode": "existing",
                    "id": ctx.get("sg_id")
                }
            
            # Log final parameters for Terraform Manager
            logger.info(f"TERRAFORM MANAGER RECEIVES:")
            logger.info(f"  VPC: {parameters.get('vpc', 'Not set')}")
            logger.info(f"  Subnet: {parameters.get('subnet', 'Not set')}")
            logger.info(f"  Security Group: {parameters.get('security_group', 'Not set')}")
            logger.info(f"  Keypair: {parameters.get('key_name')} (create_new: {parameters.get('create_new_keypair')})")
            logger.info(f"  Full parameters: {json.dumps(parameters, indent=2)}")
            
            # Create infrastructure request
            from .infrastructure import create_infrastructure_request
            
            request_data = {
                "request_identifier": request_id,
                "cloud_provider": "aws",
                "environment": cfg.get("environment", "dev"),
                "resource_type": "ec2",
                "parameters": parameters,
                "user_email": user_email,
                "department": user_info.get("department", "Unknown")
            }
            
            # Call the infrastructure creation function
            created_request_id = await create_infrastructure_request(request_data)
            
            # Reset state after successful deployment - complete fresh start
            self._initialize_user_state(user_email, preserve_conversation=False)
            
            return {
                "message": f"🚀 Awesome! Your EC2 instance is being created right now (Request: {created_request_id}).\n\nI'll notify you as soon as it's ready - usually takes about 5-10 minutes.\n\nWhat else would you like to build today?", 
                "show_text_input": True
            }
            
        except Exception as e:
            logger.exception(f"Deployment failed: {e}")
            self._initialize_user_state(user_email, preserve_conversation=True)
            return {"message": f"Oops! Something went wrong: {str(e)}\n\nNo worries though - let's try again. What would you like to create?", "show_text_input": True}

    def _generate_keypair_name(self, user_info: Dict) -> str:
        """Generate unique keypair name with timestamp to avoid AWS collisions"""
        import time
        department = user_info.get("department", "user").lower().replace(" ", "-").replace("_", "-")
        timestamp = str(int(time.time()))[-6:]
        return f"auto-{department}-{timestamp}"

    async def _send_environment_approval_request(self, user_email: str, user_info: Dict, env: str) -> Dict[str, Any]:
        """Send environment approval request to manager"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/environment/request-access",
                    params={"environment": env},
                    headers={"Authorization": f"Bearer {user_info.get('jwt_token', '')}"},
                    timeout=15.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "message": f"✅ Perfect! I've sent the {env.upper()} environment approval request to your manager ({user_info.get('manager_email', 'manager')}). You'll typically get approval within a few hours. I'll notify you as soon as it's approved!",
                        "show_text_input": True
                    }
                else:
                    error_data = response.json()
                    error_msg = error_data.get("detail", f"Failed to request {env.upper()} access")
                    
                    if "already have access" in error_msg:
                        return {
                            "message": f"Great news! You already have {env.upper()} environment access. Ready to create an instance?",
                            "show_text_input": True
                        }
                    elif "pending request" in error_msg:
                        return {
                            "message": f"You already have a pending {env.upper()} access request. Please wait for manager approval.",
                            "show_text_input": True
                        }
                    else:
                        return {
                            "message": f"Unable to send approval request: {error_msg}. Please try again or contact support.",
                            "show_text_input": True
                        }
                        
        except Exception as e:
            logger.error(f"Error sending environment approval request: {e}")
            return {
                "message": f"Sorry, I couldn't send the {env.upper()} approval request right now. Please try again in a moment.",
                "show_text_input": True
            }

    # -------------------- HELPER METHODS --------------------

    def _is_allowed_in_env(self, user_info: Dict[str, Any], env: str, cfg: Dict[str, Any]) -> bool:
        """Check if configuration is allowed in environment"""
        limits = get_department_limits("aws", env, user_info.get("department", ""))
        if limits.get("allowed_instance_types") and cfg.get("instance_type") not in limits["allowed_instance_types"]:
            return False
        if limits.get("allowed_regions") and cfg.get("region") not in limits["allowed_regions"]:
            return False
        mx = limits.get("max_storage_gb")
        if isinstance(mx, int) and cfg.get("storage_size") and cfg["storage_size"] > mx:
            return False
        return True

    async def _compute_cost(self, cfg: Dict[str, Any], scope: str = "overall") -> Optional[str]:
        """Compute cost using MCP service"""
        try:
            if not cfg:
                return None
            storage = cfg.get("storage_size")
            if isinstance(storage, str):
                m = re.search(r'(\d+)', storage)
                storage = int(m.group(1)) if m else None
            complete = all(p in cfg and cfg[p] not in (None,"",0) for p in REQ_FIELDS)
            payload = {
                "environment": cfg.get("environment") or "dev",
                "instance_type": cfg.get("instance_type") or "t3.micro",
                "operating_system": cfg.get("operating_system") or "ubuntu",
                "storage_size": storage or 20,
                "region": cfg.get("region") or "us-east-1"
            }
            async with httpx.AsyncClient() as client:
                res = await client.post("http://localhost:8001/mcp/calculate-cost", json=payload, timeout=8.0)
            if res.status_code != 200:
                return None
            data = res.json()
            b = data.get("breakdown", {})
            monthly = data.get("monthly_cost")
            ic = b.get("instance_monthly")
            sc = b.get("storage_monthly")
            header = "Estimated monthly cost" if complete else "Partial estimate (based on available parameters)"
            if scope == "storage" and sc is not None:
                return f"{header} — Storage only: ${sc:.2f}"
            if scope == "instance" and ic is not None:
                return f"{header} — Instance only: ${ic:.2f}"
            if monthly is not None and ic is not None and sc is not None:
                return f"{header}: Instance ${ic:.2f} + Storage ${sc:.2f} = ${monthly:.2f}"
            return None
        except Exception:
            return None