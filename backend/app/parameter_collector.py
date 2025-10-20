"""
Parameter Collector - Minimal input collection for different scenarios
Handles VPC, Subnet, Security Groups, and Key Pairs after technical/cost approval
"""

import logging
import re
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .aws_fetcher_async import AWSResourceFetcher
from .permissions import check_environment_access

logger = logging.getLogger(__name__)

class ParameterCollector:
    """Collects minimal parameters for different deployment scenarios"""
    
    def __init__(self):
        self.scenarios = {
            "quick_dev": self._quick_dev_scenario,
            "custom_networking": self._custom_networking_scenario,
            "production_secure": self._production_secure_scenario,
            "natural_language": self._natural_language_scenario,
            "s3_creation": self._s3_creation_scenario,
            "lambda_creation": self._lambda_creation_scenario
        }
    
    # ===== MAIN COLLECTION METHODS =====
    
    async def collect_parameters(self, scenario: str, user_input: str, user_info: Dict, 
                               current_state: Dict = None) -> Dict[str, Any]:
        """Main parameter collection entry point"""
        
        if scenario not in self.scenarios:
            scenario = "quick_dev"  # Default fallback
        
        state = current_state or self._initialize_state()
        
        try:
            return await self.scenarios[scenario](user_input, user_info, state)
        except Exception as e:
            logger.error(f"Parameter collection error in {scenario}: {e}")
            return self._error_response(f"Collection failed: {str(e)}")
    
    def _initialize_state(self) -> Dict[str, Any]:
        """Initialize collection state"""
        return {
            "collected": {},
            "missing": ["environment", "instance_type", "operating_system", "storage_size", "region"],
            "step": "environment",
            "resources": {},
            "validated": False,
            "created_at": datetime.now()
        }
    
    # ===== SCENARIO IMPLEMENTATIONS =====
    
    async def _quick_dev_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """Scenario 1: Quick development server with minimal questions"""
        
        # Extract parameters from input
        extracted = self._extract_basic_parameters(user_input)
        state["collected"].update(extracted)
        
        # Auto-fill defaults for dev environment
        if not state["collected"].get("environment"):
            state["collected"]["environment"] = "dev"
        
        # Update missing parameters
        state["missing"] = self._get_missing_basic_parameters(state["collected"])
        
        # If basic parameters complete, handle networking
        if not state["missing"]:
            return await self._handle_quick_networking(state, user_info)
        
        # Ask for next missing parameter
        next_param = state["missing"][0]
        return self._ask_for_parameter(next_param, state["collected"])
    
    async def _custom_networking_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """Scenario 2: Custom networking with resource selection"""
        
        # First collect basic parameters
        if state["step"] in ["environment", "instance_type", "operating_system", "storage_size", "region"]:
            return await self._collect_basic_parameter(user_input, state, user_info)
        
        # Then handle networking steps
        if state["step"] == "vpc_selection":
            return await self._handle_vpc_selection(user_input, state, user_info)
        elif state["step"] == "subnet_selection":
            return await self._handle_subnet_selection(user_input, state, user_info)
        elif state["step"] == "sg_selection":
            return await self._handle_sg_selection(user_input, state, user_info)
        elif state["step"] == "keypair_selection":
            return await self._handle_keypair_selection(user_input, state, user_info)
        
        return self._complete_collection(state)
    
    async def _production_secure_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """Scenario 3: Production deployment with security validation"""
        
        # Check production access first
        if not await self._check_production_access(user_info):
            return self._request_production_access(user_info)
        
        # Collect parameters with production constraints
        extracted = self._extract_basic_parameters(user_input)
        
        # Apply production validation
        validation = self._validate_production_parameters(extracted)
        if not validation["valid"]:
            return self._validation_error_response(validation)
        
        state["collected"].update(extracted)
        state["missing"] = self._get_missing_basic_parameters(state["collected"])
        
        # Production requires custom networking
        if not state["missing"]:
            return await self._handle_production_networking(state, user_info)
        
        next_param = state["missing"][0]
        return self._ask_for_production_parameter(next_param, state["collected"])
    
    async def _natural_language_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """Scenario 4: Natural language processing for parameter extraction"""
        
        # Extract all possible parameters from natural language
        extracted = self._extract_from_natural_language(user_input)
        
        if extracted:
            state["collected"].update(extracted)
            state["missing"] = self._get_missing_basic_parameters(state["collected"])
            
            # Confirm extracted parameters
            confirmation_msg = self._format_confirmation_message(extracted)
            
            if not state["missing"]:
                return {
                    "message": f"{confirmation_msg} Ready to configure networking?",
                    "buttons": [
                        {"text": "Yes, Continue", "action": "continue_networking"},
                        {"text": "Modify", "action": "modify"}
                    ],
                    "show_text_input": True,
                    "state": state
                }
            else:
                missing_params = ", ".join(state["missing"])
                return {
                    "message": f"{confirmation_msg} Still need: {missing_params}. What would you like to specify?",
                    "show_text_input": True,
                    "state": state
                }
        
        # If no parameters extracted, ask for clarification
        return {
            "message": "I can help you create an EC2 instance. What environment do you need? (dev/qa/prod)",
            "show_text_input": True,
            "state": state
        }
    
    # ===== PARAMETER EXTRACTION METHODS =====
    
    def _extract_basic_parameters(self, user_input: str) -> Dict[str, Any]:
        """Extract basic EC2 parameters from user input"""
        
        params = {}
        text = user_input.lower().strip()
        
        # Environment detection
        if any(env in text for env in ["dev", "development"]):
            params["environment"] = "dev"
        elif any(env in text for env in ["qa", "quality", "test"]):
            params["environment"] = "qa"
        elif any(env in text for env in ["prod", "production"]):
            params["environment"] = "prod"
        
        # Instance type detection
        instance_pattern = r'(t3\.\w+|m5\.\w+|c5\.\w+|r5\.\w+)'
        if match := re.search(instance_pattern, text):
            params["instance_type"] = match.group(1)
        
        # Operating system detection
        if "ubuntu" in text:
            params["operating_system"] = "ubuntu"
        elif "amazon" in text and "linux" in text:
            params["operating_system"] = "amazon-linux"
        elif "windows" in text:
            params["operating_system"] = "windows"
        
        # Storage size detection
        storage_patterns = [r'(\d+)\s*gb', r'(\d+)gb', r'^(\d+)$']
        for pattern in storage_patterns:
            if match := re.search(pattern, text, re.IGNORECASE):
                size = int(match.group(1))
                if 1 <= size <= 2000:
                    params["storage_size"] = size
                    break
        
        # Region detection
        regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
        for region in regions:
            if region in text:
                params["region"] = region
                break
        
        return params
    
    def _extract_from_natural_language(self, user_input: str) -> Dict[str, Any]:
        """Advanced natural language parameter extraction"""
        
        params = self._extract_basic_parameters(user_input)
        text = user_input.lower()
        
        # Keypair name extraction
        keypair_patterns = [
            r'keypair called ([a-zA-Z0-9-_]+)',
            r'key pair named ([a-zA-Z0-9-_]+)',
            r'ssh key ([a-zA-Z0-9-_]+)'
        ]
        
        for pattern in keypair_patterns:
            if match := re.search(pattern, text):
                params["keypair_name"] = match.group(1)
                break
        
        # Networking preferences
        if "default" in text and ("vpc" in text or "network" in text):
            params["networking_preference"] = "default"
        elif "existing" in text and ("vpc" in text or "network" in text):
            params["networking_preference"] = "existing"
        elif "custom" in text and ("vpc" in text or "network" in text):
            params["networking_preference"] = "custom"
        
        # Security preferences
        if "private" in text and "subnet" in text:
            params["subnet_type"] = "private"
        elif "public" in text and "subnet" in text:
            params["subnet_type"] = "public"
        
        return params
    
    # ===== NETWORKING HANDLERS =====
    
    async def _handle_quick_networking(self, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle networking for quick deployment scenario"""
        
        # Auto-configure with defaults
        networking_config = {
            "vpc": {"mode": "default"},
            "subnet": {"mode": "default", "type": "public"},
            "security_group": {"mode": "default"},
            "key_pair": {
                "type": "new",
                "name": self._generate_keypair_name(user_info)
            }
        }
        
        state["collected"]["networking"] = networking_config
        
        return {
            "message": f"Configuration complete! Using default networking and auto-generated keypair: {networking_config['key_pair']['name']}. Ready to deploy?",
            "buttons": [
                {"text": "Deploy Now", "action": "deploy"},
                {"text": "Customize Networking", "action": "customize"}
            ],
            "show_text_input": True,
            "state": state
        }
    
    async def _handle_vpc_selection(self, user_input: str, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle VPC selection"""
        
        environment = state["collected"].get("environment", "dev")
        region = state["collected"].get("region", "us-east-1")
        
        # Fetch available VPCs
        fetcher = AWSResourceFetcher(environment, region)
        vpcs = await fetcher.get_vpcs()
        
        # Filter VPCs based on environment
        if environment == "prod":
            vpcs = [v for v in vpcs if "prod" in v["name"].lower() and not v["is_default"]]
        
        if not vpcs:
            return {
                "message": "No suitable VPCs found. Using default VPC.",
                "state": state
            }
        
        # Present VPC options
        buttons = []
        for vpc in vpcs[:5]:  # Limit to 5 options
            buttons.append({
                "text": f"{vpc['name']} ({vpc['cidr']})",
                "value": vpc["id"],
                "data": vpc
            })
        
        state["step"] = "subnet_selection"
        state["resources"]["vpcs"] = vpcs
        
        return {
            "message": "Select VPC:",
            "buttons": buttons,
            "show_text_input": False,
            "state": state
        }
    
    async def _handle_subnet_selection(self, user_input: str, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle subnet selection"""
        
        # Get selected VPC ID from previous step
        selected_vpc_id = user_input  # This would be the VPC ID from button click
        
        environment = state["collected"].get("environment", "dev")
        region = state["collected"].get("region", "us-east-1")
        
        # Fetch subnets for selected VPC
        fetcher = AWSResourceFetcher(environment, region)
        subnets = await fetcher.get_subnets(selected_vpc_id)
        
        # Filter subnets based on environment requirements
        if environment == "prod":
            # Prefer private subnets for production
            private_subnets = [s for s in subnets if not s["public"]]
            if private_subnets:
                subnets = private_subnets
        
        buttons = []
        for subnet in subnets[:5]:
            subnet_type = "Private" if not subnet["public"] else "Public"
            buttons.append({
                "text": f"{subnet['name']} ({subnet_type}, {subnet['availability_zone']})",
                "value": subnet["id"],
                "data": subnet
            })
        
        state["step"] = "sg_selection"
        state["resources"]["subnets"] = subnets
        
        return {
            "message": "Select Subnet:",
            "buttons": buttons,
            "show_text_input": False,
            "state": state
        }
    
    async def _handle_sg_selection(self, user_input: str, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle security group selection"""
        
        environment = state["collected"].get("environment", "dev")
        region = state["collected"].get("region", "us-east-1")
        
        # Fetch security groups
        fetcher = AWSResourceFetcher(environment, region)
        security_groups = await fetcher.get_security_groups()
        
        # Filter by environment
        if environment == "prod":
            security_groups = [sg for sg in security_groups if "prod" in sg["name"].lower()]
        
        buttons = [{"text": "Create New Security Group", "value": "new"}]
        
        for sg in security_groups[:4]:  # 4 existing + 1 new option
            buttons.append({
                "text": f"{sg['name']} ({sg['description'][:30]}...)",
                "value": sg["id"],
                "data": sg
            })
        
        state["step"] = "keypair_selection"
        state["resources"]["security_groups"] = security_groups
        
        return {
            "message": "Select Security Group:",
            "buttons": buttons,
            "show_text_input": False,
            "state": state
        }
    
    async def _handle_keypair_selection(self, user_input: str, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle keypair selection"""
        
        environment = state["collected"].get("environment", "dev")
        region = state["collected"].get("region", "us-east-1")
        
        # Fetch existing keypairs
        fetcher = AWSResourceFetcher(environment, region)
        keypairs = await fetcher.get_keypairs()
        
        buttons = [{"text": "Create New Keypair", "value": "new"}]
        
        for kp in keypairs[:4]:  # 4 existing + 1 new option
            buttons.append({
                "text": f"{kp['name']} ({kp['type']})",
                "value": kp["name"],
                "data": kp
            })
        
        return {
            "message": "Select SSH Keypair:",
            "buttons": buttons,
            "show_text_input": True,
            "state": state
        }
    
    # ===== VALIDATION METHODS =====
    
    def _validate_production_parameters(self, params: Dict) -> Dict[str, Any]:
        """Validate parameters for production environment"""
        
        errors = []
        
        # Production instance type validation
        allowed_prod_instances = ["t3.small", "t3.medium", "t3.large", "m5.large", "m5.xlarge"]
        if params.get("instance_type") and params["instance_type"] not in allowed_prod_instances:
            errors.append(f"Instance type {params['instance_type']} not allowed in production")
        
        # Storage size validation
        if params.get("storage_size") and params["storage_size"] > 500:
            errors.append("Storage size cannot exceed 500GB in production")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
    
    async def _check_production_access(self, user_info: Dict) -> bool:
        """Check if user has production environment access"""
        try:
            return await check_environment_access(user_info.get("email", ""), "prod")
        except Exception as e:
            logger.error(f"Error checking production access: {e}")
            return False
    
    # ===== UTILITY METHODS =====
    
    def _get_missing_basic_parameters(self, collected: Dict) -> List[str]:
        """Get list of missing basic parameters"""
        required = ["environment", "instance_type", "operating_system", "storage_size", "region"]
        return [param for param in required if param not in collected or not collected[param]]
    
    def _generate_keypair_name(self, user_info: Dict) -> str:
        """Generate auto keypair name"""
        department = user_info.get("department", "user").lower().replace(" ", "-")
        random_id = uuid.uuid4().hex[:6]
        return f"auto-{department}-{random_id}"
    
    # ===== S3 AND LAMBDA SCENARIOS =====
    
    async def _s3_creation_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """S3 bucket creation scenario"""
        extracted = self._extract_s3_parameters(user_input)
        state["collected"].update(extracted)
        
        required = ["bucket_name", "environment", "region"]
        missing = [p for p in required if p not in state["collected"]]
        
        if not missing:
            return {
                "message": f"Ready to create S3 bucket '{state['collected']['bucket_name']}' in {state['collected']['environment']}?",
                "buttons": [{"text": "Create Bucket", "action": "deploy"}],
                "state": state
            }
        
        return self._ask_for_s3_parameter(missing[0], state["collected"])
    
    async def _lambda_creation_scenario(self, user_input: str, user_info: Dict, state: Dict) -> Dict[str, Any]:
        """Lambda function creation scenario"""
        extracted = self._extract_lambda_parameters(user_input)
        state["collected"].update(extracted)
        
        required = ["function_name", "runtime", "environment", "region"]
        missing = [p for p in required if p not in state["collected"]]
        
        if not missing:
            return {
                "message": f"Ready to create Lambda function '{state['collected']['function_name']}' with {state['collected']['runtime']}?",
                "buttons": [{"text": "Create Function", "action": "deploy"}],
                "state": state
            }
        
        return self._ask_for_lambda_parameter(missing[0], state["collected"])
    
    def _extract_s3_parameters(self, user_input: str) -> Dict[str, Any]:
        """Extract S3 parameters from input"""
        params = {}
        text = user_input.lower()
        
        # Bucket name extraction - improved patterns
        bucket_patterns = [
            r'bucket\s+called\s+([a-z0-9][a-z0-9.-]*[a-z0-9])',
            r'bucket\s+named\s+([a-z0-9][a-z0-9.-]*[a-z0-9])',
            r's3\s+bucket\s+([a-z0-9][a-z0-9.-]*[a-z0-9])',
            r'create\s+bucket\s+([a-z0-9][a-z0-9.-]*[a-z0-9])',
            r'bucket\s+([a-z0-9][a-z0-9.-]*[a-z0-9])'
        ]
        for pattern in bucket_patterns:
            if match := re.search(pattern, text):
                bucket_name = match.group(1)
                # Validate S3 bucket naming rules
                if (3 <= len(bucket_name) <= 63 and 
                    not bucket_name.startswith('-') and 
                    not bucket_name.endswith('-') and
                    not bucket_name.startswith('.') and
                    not bucket_name.endswith('.')):
                    params["bucket_name"] = bucket_name
                    break
        
        # Environment detection
        if "dev" in text or "development" in text: params["environment"] = "dev"
        elif "prod" in text or "production" in text: params["environment"] = "prod"
        elif "qa" in text or "test" in text: params["environment"] = "qa"
        
        # Region detection
        regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
        for region in regions:
            if region in text:
                params["region"] = region
                break
        
        # Additional S3 parameters
        if "versioning" in text or "version" in text: params["versioning_enabled"] = True
        if "public" in text: params["public_access"] = True
        if "private" in text: params["public_access"] = False
        
        return params
    
    def _extract_lambda_parameters(self, user_input: str) -> Dict[str, Any]:
        """Extract Lambda parameters from input"""
        params = {}
        text = user_input.lower()
        
        # Function name extraction - improved patterns
        func_patterns = [
            r'function\s+called\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)',
            r'function\s+named\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)',
            r'lambda\s+function\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)',
            r'create\s+function\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)',
            r'function\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)',
            r'lambda\s+([a-zA-Z0-9][a-zA-Z0-9-_]*)'
        ]
        for pattern in func_patterns:
            if match := re.search(pattern, text):
                function_name = match.group(1)
                # Validate Lambda function naming rules
                if 1 <= len(function_name) <= 64:
                    params["function_name"] = function_name
                    break
        
        # Runtime detection - more comprehensive
        if "python3.11" in text: params["runtime"] = "python3.11"
        elif "python3.10" in text: params["runtime"] = "python3.10"
        elif "python" in text: params["runtime"] = "python3.9"
        elif "nodejs20" in text: params["runtime"] = "nodejs20.x"
        elif "nodejs18" in text: params["runtime"] = "nodejs18.x"
        elif "node" in text or "javascript" in text: params["runtime"] = "nodejs18.x"
        elif "java17" in text: params["runtime"] = "java17"
        elif "java11" in text: params["runtime"] = "java11"
        elif "java" in text: params["runtime"] = "java11"
        elif "go" in text: params["runtime"] = "go1.x"
        
        # Environment detection
        if "dev" in text or "development" in text: params["environment"] = "dev"
        elif "prod" in text or "production" in text: params["environment"] = "prod"
        elif "qa" in text or "test" in text: params["environment"] = "qa"
        
        # Region detection
        regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
        for region in regions:
            if region in text:
                params["region"] = region
                break
        
        # Memory and timeout extraction
        memory_match = re.search(r'(\d+)\s*mb', text)
        if memory_match:
            memory = int(memory_match.group(1))
            if 128 <= memory <= 10240:
                params["memory_size"] = memory
        
        timeout_match = re.search(r'(\d+)\s*sec', text)
        if timeout_match:
            timeout = int(timeout_match.group(1))
            if 1 <= timeout <= 900:
                params["timeout"] = timeout
        
        return params
    
    def _ask_for_s3_parameter(self, param: str, collected: Dict) -> Dict[str, Any]:
        """Ask for S3 parameter"""
        prompts = {
            "bucket_name": "What should the S3 bucket be named?",
            "environment": "What environment? (dev/prod)",
            "region": "What region? (us-east-1/us-west-2)"
        }
        return {"message": prompts.get(param, f"Specify {param}:"), "show_text_input": True}
    
    def _ask_for_lambda_parameter(self, param: str, collected: Dict) -> Dict[str, Any]:
        """Ask for Lambda parameter"""
        prompts = {
            "function_name": "What should the Lambda function be named?",
            "runtime": "What runtime? (python3.9/nodejs18.x/java11)",
            "environment": "What environment? (dev/prod)",
            "region": "What region? (us-east-1/us-west-2)"
        }
        return {"message": prompts.get(param, f"Specify {param}:"), "show_text_input": True}
    
    def _ask_for_parameter(self, param: str, collected: Dict) -> Dict[str, Any]:
        """Ask user for specific parameter"""
        
        prompts = {
            "environment": "What environment? (dev/qa/prod)",
            "instance_type": "What instance type? (t3.micro/t3.small/t3.medium)",
            "operating_system": "What operating system? (ubuntu/amazon-linux/windows)",
            "storage_size": "Storage size in GB? (8-500)",
            "region": "What region? (us-east-1/us-west-2/eu-west-1)"
        }
        
        return {
            "message": prompts.get(param, f"Please specify {param}:"),
            "show_text_input": True,
            "current_parameter": param
        }
    
    def _format_confirmation_message(self, params: Dict) -> str:
        """Format parameter confirmation message"""
        
        formatted_params = []
        for key, value in params.items():
            if key == "storage_size":
                formatted_params.append(f"{key.replace('_', ' ')}: {value}GB")
            else:
                formatted_params.append(f"{key.replace('_', ' ')}: {value}")
        
        return f"Detected: {', '.join(formatted_params)}."
    
    def _error_response(self, message: str) -> Dict[str, Any]:
        """Return error response"""
        return {
            "message": f"Error: {message}",
            "show_text_input": True,
            "error": True
        }
    
    def _validation_error_response(self, validation: Dict) -> Dict[str, Any]:
        """Return validation error response"""
        errors = "; ".join(validation["errors"])
        return {
            "message": f"Validation failed: {errors}",
            "show_text_input": True,
            "validation_errors": validation["errors"]
        }
    
    def _complete_collection(self, state: Dict) -> Dict[str, Any]:
        """Complete parameter collection"""
        return {
            "message": "Parameter collection complete! Ready to deploy?",
            "buttons": [
                {"text": "Deploy Now", "action": "deploy"},
                {"text": "Review Configuration", "action": "review"}
            ],
            "show_text_input": True,
            "state": state,
            "complete": True
        }
    
    def _request_production_access(self, user_info: Dict) -> Dict[str, Any]:
        """Request production environment access"""
        return {
            "message": "You need production environment access. Request approval from your manager?",
            "buttons": [
                {"text": "Yes, Request Access", "action": "request_prod_access"},
                {"text": "Use DEV Instead", "action": "use_dev"}
            ],
            "show_text_input": True
        }
    
    async def _handle_production_networking(self, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Handle production networking requirements"""
        return {
            "message": "Production requires custom networking. Let's configure VPC and security settings.",
            "buttons": [
                {"text": "Select VPC", "action": "vpc_selection"},
                {"text": "Use Default", "action": "default_prod"}
            ],
            "show_text_input": False,
            "state": state
        }
    
    def _ask_for_production_parameter(self, param: str, collected: Dict) -> Dict[str, Any]:
        """Ask for production-specific parameter"""
        prod_prompts = {
            "instance_type": "Production instance type? (t3.small/t3.medium/t3.large/m5.large)",
            "storage_size": "Storage size in GB? (20-500 for production)",
            "region": "Production region? (us-east-1/us-west-2/eu-west-1)"
        }
        
        return {
            "message": prod_prompts.get(param, f"Please specify {param} for production:"),
            "show_text_input": True,
            "current_parameter": param
        }
    
    async def _collect_basic_parameter(self, user_input: str, state: Dict, user_info: Dict) -> Dict[str, Any]:
        """Collect basic parameter in custom networking scenario"""
        current_step = state["step"]
        
        # Extract parameter from input
        extracted = self._extract_basic_parameters(user_input)
        
        if current_step in extracted:
            state["collected"][current_step] = extracted[current_step]
            
            # Move to next step
            steps = ["environment", "instance_type", "operating_system", "storage_size", "region"]
            current_index = steps.index(current_step)
            
            if current_index < len(steps) - 1:
                state["step"] = steps[current_index + 1]
                return self._ask_for_parameter(state["step"], state["collected"])
            else:
                # All basic parameters collected, move to networking
                state["step"] = "vpc_selection"
                return await self._handle_vpc_selection("", state, user_info)
        
        # Parameter not found, ask again
        return self._ask_for_parameter(current_step, state["collected"])

# ===== USAGE EXAMPLES =====

async def example_usage():
    """Example usage of ParameterCollector"""
    
    collector = ParameterCollector()
    
    # Example 1: Quick dev scenario
    user_info = {"email": "dev@company.com", "department": "Engineering"}
    
    response1 = await collector.collect_parameters(
        scenario="quick_dev",
        user_input="I need a t3.micro ubuntu server in dev",
        user_info=user_info
    )
    print("Quick Dev Response:", response1)
    
    # Example 2: Natural language scenario
    response2 = await collector.collect_parameters(
        scenario="natural_language", 
        user_input="Create a t3.small ubuntu server in dev with 50GB storage in us-west-2",
        user_info=user_info
    )
    print("Natural Language Response:", response2)
    
    # Example 3: Production scenario
    response3 = await collector.collect_parameters(
        scenario="production_secure",
        user_input="I need a production web server",
        user_info=user_info
    )
    print("Production Response:", response3)

if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())