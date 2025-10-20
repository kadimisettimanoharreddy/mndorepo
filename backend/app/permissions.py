# backend/app/permissions.py

import logging
import json
import httpx
import os
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Default hardcoded permissions (as fallback)
DEFAULT_PERMISSIONS_MATRIX: Dict[str, Dict[str, Dict[str, Any]]] = {
    "aws": {
        "dev": {
            "Engineering": {
                "allowed_instance_types": ["t3.micro", "t3.small", "t3.medium", "t3.large"],
                "allowed_regions": ["us-east-1", "us-west-2", "ap-south-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 1024,
                "s3_buckets_limit": 20,
                "lambda_functions_limit": 30,
                "requires_approval": False
            },
            "DataScience": {
                "allowed_instance_types": ["t3.medium", "t3.large", "t3.xlarge"],
                "allowed_regions": ["us-east-1", "ap-south-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 3008,
                "s3_buckets_limit": 50,
                "lambda_functions_limit": 25,
                "requires_approval": False
            },
            "DevOps": {
                "allowed_instance_types": ["t3.micro", "t3.small", "t3.medium", "t3.large", "m5.large"],
                "allowed_regions": ["us-east-1", "us-west-2", "ap-south-1", "eu-west-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 3008,
                "s3_buckets_limit": 100,
                "lambda_functions_limit": 100,
                "requires_approval": False
            },
            "Finance": {
                "allowed_instance_types": ["t3.micro"],
                "allowed_regions": ["us-east-1"],
                "allowed_services": ["ec2", "s3"],
                "max_storage_gb": 50,
                "max_lambda_memory_mb": 512,
                "requires_approval": True
            },
            "Marketing": {
                "allowed_instance_types": ["t3.micro", "t3.small"],
                "allowed_regions": ["us-east-1"],
                "allowed_services": ["ec2", "s3"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 512,
                "requires_approval": True
            },
            "HR": {
                "allowed_instance_types": ["t3.micro"],
                "allowed_regions": ["us-east-1"],
                "allowed_services": ["s3"],
                "max_storage_gb": 30,
                "max_lambda_memory_mb": 256,
                "requires_approval": True
            }
        },
        "qa": {
            "Engineering": {
                "allowed_instance_types": ["t3.small", "t3.medium"],
                "allowed_regions": ["us-east-1", "ap-south-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 50,
                "max_lambda_memory_mb": 512,
                "s3_buckets_limit": 15,
                "lambda_functions_limit": 20,
                "requires_approval": True
            },
            "DataScience": {
                "allowed_instance_types": ["t3.large", "t3.xlarge"],
                "allowed_regions": ["us-east-1"],
                "max_storage_gb": 100,
                "requires_approval": True
            },
            "DevOps": {
                "allowed_instance_types": ["t3.small", "t3.medium", "t3.large"],
                "allowed_regions": ["us-east-1", "ap-south-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 1024,
                "s3_buckets_limit": 50,
                "lambda_functions_limit": 50,
                "requires_approval": True
            },
            "Finance": {
                "allowed_instance_types": ["t3.micro"],
                "allowed_regions": ["us-east-1"],
                "max_storage_gb": 30,
                "requires_approval": True
            },
            "Marketing": {
                "allowed_instance_types": ["t3.micro"],
                "allowed_regions": ["us-east-1"],
                "max_storage_gb": 50,
                "requires_approval": True
            },
            "HR": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            }
        },
        "prod": {
            "Engineering": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            },
            "DataScience": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            },
            "DevOps": {
                "allowed_instance_types": ["t3.medium", "t3.large", "m5.large"],
                "allowed_regions": ["us-east-1"],
                "allowed_services": ["ec2", "s3", "lambda"],
                "max_storage_gb": 100,
                "max_lambda_memory_mb": 2048,
                "s3_buckets_limit": 200,
                "lambda_functions_limit": 200,
                "requires_approval": True
            },
            "Finance": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            },
            "Marketing": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            },
            "HR": {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            }
        }
    }
}

# Global variable to track permissions source
PERMISSIONS_SOURCE = "NOT_LOADED"
PERMISSIONS_MATRIX = DEFAULT_PERMISSIONS_MATRIX
async def fetch_permissions_from_github() -> Dict[str, Any]:
    """
    Fetch permissions.json from GitHub repository using httpx
    """
    global PERMISSIONS_SOURCE
    
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = os.getenv("GITHUB_REPO_OWNER")
        repo_name = os.getenv("GITHUB_REPO_NAME")
        
        if not all([github_token, repo_owner, repo_name]):
            logger.warning("GitHub credentials not found in environment variables")
            return None
        
        # CORRECT PATH: Add 'backend/' to the path
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/backend/terraform/environments/aws/configs/permissions.json"
        
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AIOps-Platform"
        }
        
        logger.info(f"Fetching permissions from GitHub: {repo_owner}/{repo_name}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
            
            if response.status_code == 200:
                data = response.json()
                import base64
                content = base64.b64decode(data['content']).decode('utf-8')
                json_permissions = json.loads(content)
                
                PERMISSIONS_SOURCE = "GITHUB_REPO"
                logger.info("Successfully loaded permissions from GitHub repository")
                logger.info(f"Loaded environments: {list(json_permissions.get('aws', {}).keys())}")
                
                return json_permissions
            else:
                logger.warning(f"GitHub API returned status {response.status_code}")
                return None
                    
    except Exception as e:
        logger.error(f"Error fetching permissions from GitHub: {e}")
        return None
    
async def load_permissions() -> Dict[str, Any]:
    """
    Load permissions with only two cases:
    1. Try GitHub repository
    2. Fallback to default permissions
    """
    global PERMISSIONS_SOURCE
    
    logger.info("Starting permissions loading process")
    
    # Step 1: Try GitHub repository
    logger.info("Step 1: Attempting to fetch from GitHub repository")
    github_permissions = await fetch_permissions_from_github()
    
    if github_permissions is not None:
        return github_permissions
    
    # Step 2: Fallback to defaults
    PERMISSIONS_SOURCE = "DEFAULT_FALLBACK"
    logger.info("Step 2: Using default permissions (fallback)")
    return DEFAULT_PERMISSIONS_MATRIX

async def initialize_permissions():
    """
    Initialize permissions at application startup
    """
    global PERMISSIONS_MATRIX
    
    logger.info("INITIALIZING PERMISSIONS SYSTEM")
    logger.info("=" * 50)
    
    PERMISSIONS_MATRIX = await load_permissions()
    
    logger.info("=" * 50)
    logger.info(f"PERMISSIONS SOURCE: {PERMISSIONS_SOURCE}")
    logger.info(f"Environments loaded: {list(PERMISSIONS_MATRIX.get('aws', {}).keys())}")
    logger.info("PERMISSIONS INITIALIZATION COMPLETE")
    logger.info("=" * 50)

async def reload_permissions():
    """
    Reload permissions from GitHub repository
    """
    global PERMISSIONS_MATRIX
    logger.info("Reloading permissions")
    
    try:
        new_permissions = await load_permissions()
        PERMISSIONS_MATRIX = new_permissions
        logger.info(f"Permissions reloaded successfully from: {PERMISSIONS_SOURCE}")
        return True
    except Exception as e:
        logger.error(f"Error reloading permissions: {e}")
        return False

def get_permissions_status() -> Dict[str, Any]:
    """
    Return current permissions status for API endpoint
    """
    return {
        "source": PERMISSIONS_SOURCE,
        "environments_loaded": list(PERMISSIONS_MATRIX.get('aws', {}).keys()),
        "timestamp": datetime.utcnow().isoformat()
    }



def get_department_limits(cloud_provider: str, environment: str, department: str) -> Dict[str, Any]:
    """
    Get department limits from the current permissions matrix (JSON-loaded or default).
    """
    try:
        cloud_provider = (cloud_provider or "aws").lower().strip()
        environment = (environment or "dev").lower().strip()
        department = (department or "").strip()
        
        if not department:
            return {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            }
        
        cloud_limits = PERMISSIONS_MATRIX.get(cloud_provider, {})
        env_limits = cloud_limits.get(environment, {})
        dept_limits = env_limits.get(department, {})
        
        if not dept_limits:
            return {
                "allowed_instance_types": [],
                "allowed_regions": [],
                "max_storage_gb": 0,
                "requires_approval": True
            }
        
        return dept_limits
        
    except Exception as e:
        logger.error(f"Error getting department limits: {e}")
        return {
            "allowed_instance_types": [],
            "allowed_regions": [],
            "max_storage_gb": 0,
            "requires_approval": True
        }

def _parse_iso_to_utc_naive(iso_str: str) -> datetime:
    """
    Parse an ISO datetime string, handle 'Z', return a UTC-naive datetime object.
    Raise ValueError if parsing fails.
    """
    if not iso_str or not isinstance(iso_str, str):
        raise ValueError("Invalid ISO string")
    if iso_str.endswith("Z"):
        iso_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def check_environment_access(user_info: Dict[str, Any], environment: str) -> bool:
    """
    Return True if the user has access to the given environment and the access hasn't expired.
    This function is expiration-aware: it checks `user_info["environment_expiry"]` (ISO strings)
    and treats access as revoked if expiry is in the past.
    """
    try:
        if not environment:
            return False
            
        environment = environment.lower().strip()
        
        env_access = user_info.get("environment_access", {})
        env_expiry = user_info.get("environment_expiry", {}) or {}
        
        if isinstance(env_access, dict) and environment in env_access:
            access_granted = bool(env_access.get(environment))
            
            if access_granted and isinstance(env_expiry, dict) and environment in env_expiry:
                expiry_str = env_expiry.get(environment)
                if expiry_str:
                    try:
                        expiry_date = _parse_iso_to_utc_naive(expiry_str)
                        if datetime.utcnow() > expiry_date:
                            return False
                    except Exception:
                        pass
            
            return access_granted
        
        department = (user_info.get("department") or "").strip()
        if not department:
            return False
        
        limits = get_department_limits("aws", environment, department)
        requires_approval = limits.get("requires_approval", True)
        
        if environment in ("dev", "qa") and not requires_approval:
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking environment access: {e}")
        return False

def can_create_resource(user_info: Dict[str, Any], params: Dict[str, Any]) -> bool:
    try:
        if not isinstance(params, dict):
            return False
        
        cloud = params.get("cloud_provider", "aws")
        environment = params.get("environment")
        resource_type = params.get("resource_type", "ec2")
        region = params.get("region") 
        
        if not environment:
            return False
        
        if not check_environment_access(user_info, environment):
            return False
        
        department = user_info.get("department", "")
        limits = get_department_limits(cloud, environment, department)
        
        # Resource-specific validation
        if resource_type == "ec2":
            instance_type = params.get("instance_type")
            storage_size = params.get("storage_size")
            
            if instance_type:
                allowed_types = limits.get("allowed_instance_types", [])
                if allowed_types and instance_type not in allowed_types:
                    return False
            
            if storage_size is not None:
                max_storage = limits.get("max_storage_gb")
                if max_storage is not None and storage_size > max_storage:
                    return False
        
        elif resource_type == "s3":
            # S3 specific validation
            bucket_name = params.get("bucket_name")
            if not bucket_name:
                return False
            
            # Check if S3 is allowed for department
            allowed_services = limits.get("allowed_services", ["ec2", "s3", "lambda"])
            if "s3" not in allowed_services:
                return False
        
        elif resource_type == "lambda":
            # Lambda specific validation
            function_name = params.get("function_name")
            if not function_name:
                return False
            
            # Check if Lambda is allowed for department
            allowed_services = limits.get("allowed_services", ["ec2", "s3", "lambda"])
            if "lambda" not in allowed_services:
                return False
            
            # Check memory limits
            memory_size = params.get("memory_size", 128)
            max_memory = limits.get("max_lambda_memory_mb", 3008)
            if memory_size > max_memory:
                return False
        
        # Common validations
        if region:
            allowed_regions = limits.get("allowed_regions", [])
            if allowed_regions and region not in allowed_regions:
                return False
        
        if limits.get("requires_approval", False) and environment == "prod":
            env_access = user_info.get("environment_access", {})
            if not env_access.get("prod", False):
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error in can_create_resource: {e}")
        return False