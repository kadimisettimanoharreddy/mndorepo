import re
import logging
from typing import Dict, Any, List
import requests

logger = logging.getLogger(__name__)

class EC2Analyzer:
    def __init__(self):
        self.os_patterns = {
            "ubuntu": ["ubuntu", "ubunto", "ubunut"],
            "amazon-linux": ["amazon", "linux", "amzn", "amazon-linux"],
            "windows": ["windows", "win", "microsoft"]
        }
        
        self.instance_patterns = [
            r't[2-3]\.[a-z]+',
            r'm[4-5]\.[a-z]+', 
            r'c[4-5]\.[a-z]+',
            r'r[4-5]\.[a-z]+',
            r'i[3-4]\.[a-z]+'
        ]
        
        self.region_patterns = [
            r'us-[a-z]+-\d+',
            r'eu-[a-z]+-\d+',
            r'ap-[a-z]+-\d+'
        ]
    
    def analyze_request(self, user_input: str, context: str, user_info: Dict) -> Dict[str, Any]:
        """Analyze EC2 request with dynamic parameter extraction and validation"""
        
        user_input_lower = user_input.lower()
        
        # Extract parameters
        sample_config = {}
        
        # Operating System
        os_type = self._extract_os(user_input_lower)
        if os_type:
            sample_config["operating_system"] = os_type
        
        # Instance Type
        instance_type = self._extract_instance_type(user_input_lower)
        if instance_type:
            sample_config["instance_type"] = instance_type
        
        # Region
        region = self._extract_region(user_input_lower)
        if region:
            sample_config["region"] = region
        
        # Environment
        environment = self._extract_environment(user_input_lower)
        if environment:
            sample_config["environment"] = environment
        
        # Storage
        storage_size = self._extract_storage(user_input_lower)
        if storage_size:
            sample_config["storage_size"] = storage_size
        
        # Validate OS and region combination if both present
        if sample_config.get("operating_system") and sample_config.get("region"):
            validation_result = self._validate_os_region_sync(
                sample_config["operating_system"], 
                sample_config["region"]
            )
            
            if not validation_result.get("valid"):
                return {
                    "status": "validation_error",
                    "validation_errors": [validation_result.get("message", "OS not supported in region")],
                    "sample_config": sample_config
                }
        
        return {
            "status": "success",
            "sample_config": sample_config,
            "extracted_count": len(sample_config)
        }
    
    def _extract_os(self, text: str) -> str:
        """Extract operating system from text"""
        for os_type, patterns in self.os_patterns.items():
            if any(pattern in text for pattern in patterns):
                return os_type
        return None
    
    def _extract_instance_type(self, text: str) -> str:
        """Extract instance type from text"""
        for pattern in self.instance_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
    
    def _extract_region(self, text: str) -> str:
        """Extract region from text"""
        for pattern in self.region_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
    
    def _extract_environment(self, text: str) -> str:
        """Extract environment from text"""
        if any(word in text for word in ["dev", "development"]):
            return "dev"
        elif any(word in text for word in ["prod", "production"]):
            return "prod"
        elif any(word in text for word in ["qa", "test", "testing"]):
            return "qa"
        return None
    
    def _extract_storage(self, text: str) -> int:
        """Extract storage size from text"""
        storage_match = re.search(r'(\d+)\s*gb', text)
        if storage_match:
            return int(storage_match.group(1))
        return None
    
    def _validate_os_region_sync(self, os_type: str, region: str) -> Dict[str, Any]:
        """Validate OS availability in region via MCP service (synchronous)"""
        try:
            response = requests.post(
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
    
    def explain_configuration(self, user_input: str, config: Dict[str, Any]) -> str:
        """Generate explanation of extracted configuration"""
        
        parts = []
        
        if config.get("instance_type"):
            parts.append(f"I've set the instance type to {config['instance_type']}")
        
        if config.get("operating_system"):
            os_display = config["operating_system"].replace("-", " ").title()
            parts.append(f"using {os_display}")
        
        if config.get("storage_size"):
            parts.append(f"with {config['storage_size']}GB storage")
        
        if config.get("region"):
            parts.append(f"in {config['region']} region")
        
        if config.get("environment"):
            parts.append(f"for {config['environment'].upper()} environment")
        
        if parts:
            return "Perfect! " + ", ".join(parts) + "."
        else:
            return "I'm ready to help you configure your EC2 instance."