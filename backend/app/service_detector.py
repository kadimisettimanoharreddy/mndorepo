"""
Service Detection - Detect AWS service type from user input
"""

import re
from typing import Dict, Optional

class ServiceDetector:
    """Detect AWS service type from user messages"""
    
    def __init__(self):
        self.service_patterns = {
            "s3": [
                r"s3\s+bucket", r"bucket\s+called", r"bucket\s+named", 
                r"create\s+bucket", r"s3\s+storage", r"object\s+storage",
                r"file\s+storage", r"bucket\s+for"
            ],
            "lambda": [
                r"lambda\s+function", r"function\s+called", r"function\s+named",
                r"create\s+function", r"serverless\s+function", r"aws\s+lambda",
                r"lambda\s+with", r"function\s+with"
            ],
            "ec2": [
                r"ec2\s+instance", r"instance\s+called", r"server\s+called",
                r"create\s+instance", r"virtual\s+machine", r"compute\s+instance",
                r"web\s+server", r"application\s+server", r"ubuntu\s+server",
                r"windows\s+server", r"amazon\s+linux", r"t[2-3]\.[a-z]+",
                r"create.*server", r"want.*server", r"need.*server"
            ]
        }
    
    def detect_service(self, message: str) -> str:
        """Detect service type from message"""
        msg_lower = message.lower()
        
        # Check for explicit service mentions first
        for service, patterns in self.service_patterns.items():
            for pattern in patterns:
                if re.search(pattern, msg_lower):
                    return service
        
        # Check for service-specific keywords with priority order
        # EC2 keywords (highest priority for server/instance)
        if any(word in msg_lower for word in ["ec2", "instance", "server", "virtual machine", "compute"]):
            return "ec2"
        # S3 keywords (specific to storage)
        elif any(word in msg_lower for word in ["s3", "bucket"]):
            return "s3"
        # Lambda keywords
        elif any(word in msg_lower for word in ["lambda", "function", "serverless"]):
            return "lambda"
        # Generic storage - only if no server/instance keywords
        elif "storage" in msg_lower and not any(word in msg_lower for word in ["server", "instance", "ec2"]):
            return "s3"
        
        # Default to EC2 if unclear
        return "ec2"
    
    def extract_service_parameters(self, message: str, service_type: str) -> Dict:
        """Extract service-specific parameters"""
        msg_lower = message.lower()
        params = {}
        
        if service_type == "s3":
            # Extract bucket name
            bucket_patterns = [
                r'bucket\s+called\s+([a-z0-9][a-z0-9-]*[a-z0-9])',
                r'bucket\s+named\s+([a-z0-9][a-z0-9-]*[a-z0-9])',
                r's3\s+bucket\s+([a-z0-9][a-z0-9-]*[a-z0-9])',
                r'bucket\s+([a-z0-9][a-z0-9-]*[a-z0-9])'
            ]
            
            for pattern in bucket_patterns:
                match = re.search(pattern, msg_lower)
                if match:
                    bucket_name = match.group(1)
                    if 3 <= len(bucket_name) <= 63:
                        params["bucket_name"] = bucket_name
                        break
            
            # Extract S3 specific parameters
            if "versioning" in msg_lower or "version" in msg_lower:
                params["versioning_enabled"] = True
            else:
                params["versioning_enabled"] = False
            
            if "public" in msg_lower:
                params["public_access"] = True
            elif "private" in msg_lower:
                params["public_access"] = False
            else:
                params["public_access"] = False  # Default private
            
            # Storage class detection
            if "standard_ia" in msg_lower or "infrequent" in msg_lower:
                params["storage_class"] = "STANDARD_IA"
            elif "glacier" in msg_lower:
                params["storage_class"] = "GLACIER"
            else:
                params["storage_class"] = "STANDARD"
        
        elif service_type == "lambda":
            # Extract function name
            func_patterns = [
                r'function\s+called\s+([a-z0-9][a-z0-9-_]*[a-z0-9])',
                r'function\s+named\s+([a-z0-9][a-z0-9-_]*[a-z0-9])',
                r'lambda\s+function\s+([a-z0-9][a-z0-9-_]*[a-z0-9])',
                r'function\s+([a-z0-9][a-z0-9-_]*[a-z0-9])'
            ]
            
            for pattern in func_patterns:
                match = re.search(pattern, msg_lower)
                if match:
                    func_name = match.group(1)
                    if 1 <= len(func_name) <= 64:
                        params["function_name"] = func_name
                        break
            
            # Extract runtime
            if "python" in msg_lower:
                if "python3.11" in msg_lower:
                    params["runtime"] = "python3.11"
                elif "python3.10" in msg_lower:
                    params["runtime"] = "python3.10"
                else:
                    params["runtime"] = "python3.9"
            elif "node" in msg_lower or "javascript" in msg_lower:
                if "nodejs20" in msg_lower:
                    params["runtime"] = "nodejs20.x"
                else:
                    params["runtime"] = "nodejs18.x"
            elif "java" in msg_lower:
                if "java17" in msg_lower:
                    params["runtime"] = "java17"
                else:
                    params["runtime"] = "java11"
            elif "go" in msg_lower:
                params["runtime"] = "go1.x"
            
            # Extract handler
            handler_match = re.search(r'handler\s+([a-zA-Z0-9_.]+)', msg_lower)
            if handler_match:
                params["handler"] = handler_match.group(1)
            else:
                params["handler"] = "index.lambda_handler"  # Default
            
            # Extract timeout
            timeout_match = re.search(r'timeout\s+(\d+)', msg_lower)
            if timeout_match:
                timeout = int(timeout_match.group(1))
                if 1 <= timeout <= 900:
                    params["timeout"] = timeout
            else:
                params["timeout"] = 30  # Default
            
            # Extract memory
            memory_match = re.search(r'memory\s+(\d+)', msg_lower)
            if memory_match:
                memory = int(memory_match.group(1))
                if 128 <= memory <= 10240:
                    params["memory_size"] = memory
            else:
                params["memory_size"] = 128  # Default
        
        elif service_type == "ec2":
            # Extract instance type
            instance_match = re.search(r't[2-3]\.[a-z]+|m[4-5]\.[a-z]+|c[4-5]\.[a-z]+', msg_lower)
            if instance_match:
                params["instance_type"] = instance_match.group(0)
            
            # Extract operating system
            if "ubuntu" in msg_lower:
                params["operating_system"] = "ubuntu"
            elif "windows" in msg_lower:
                params["operating_system"] = "windows"
            elif "amazon" in msg_lower or "linux" in msg_lower:
                params["operating_system"] = "amazon-linux"
            
            # Extract storage size
            storage_match = re.search(r'(\d+)\s*gb', msg_lower)
            if storage_match:
                params["storage_size"] = int(storage_match.group(1))
        
        # Extract common parameters for all services
        if "dev" in msg_lower or "development" in msg_lower:
            params["environment"] = "dev"
        elif "prod" in msg_lower or "production" in msg_lower:
            params["environment"] = "prod"
        elif "qa" in msg_lower or "test" in msg_lower:
            params["environment"] = "qa"
        
        # Extract region
        regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
        for region in regions:
            if region in msg_lower:
                params["region"] = region
                break
        
        return params