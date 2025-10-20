import os
import errno
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import asyncio

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT_ENV = "REPO_ROOT"

def find_repo_root(start: Optional[Path] = None, max_up: int = 8) -> Optional[Path]:
    env_root = os.getenv(REPO_ROOT_ENV)
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if p.exists():
            logger.info("find_repo_root: using REPO_ROOT env -> %s", p)
            return p

    p = (start or Path.cwd()).resolve()
    for _ in range(max_up + 1):
        if (p / "terraform").exists() or (p / ".git").exists():
            logger.info("find_repo_root: detected repo root at %s", p)
            return p
        if p.parent == p:
            break
        p = p.parent
    logger.warning("find_repo_root: repo root not found from %s", start or Path.cwd())
    return None

def _ensure_dir(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def _get_user_info(user: Optional[Any], request_obj: Optional[Any] = None, params: Dict[str, Any] = None) -> Dict[str, str]:
    user_info = {
        "department": "unknown",
        "email": "system@aiops-platform.com",
        "name": "system"
    }
    
    # FIRST: Check params for user values (highest priority)
    if params:
        if params.get("department"):
            user_info["department"] = params["department"]
        if params.get("created_by"):
            user_info["email"] = params["created_by"]
            user_info["name"] = params["created_by"].split("@")[0].replace(".", "-")
    
    # SECOND: Check user object
    if user:
        if not params or not params.get("department"):
            user_info["department"] = getattr(user, "department", user_info["department"])
        if not params or not params.get("created_by"):
            user_info["email"] = getattr(user, "email", user_info["email"])
            user_info["name"] = getattr(user, "name", user_info["name"])
    
    # THIRD: Check request object
    elif request_obj and (not params or not params.get("created_by")):
        if hasattr(request_obj, 'user_email') and request_obj.user_email:
            user_info["email"] = request_obj.user_email
        elif hasattr(request_obj, 'created_by') and request_obj.created_by:
            user_info["email"] = request_obj.created_by
            
        if user_info["email"] != "system@aiops-platform.com":
            user_info["name"] = user_info["email"].split("@")[0].replace(".", "-")
    
    # Ensure no empty values
    if not user_info["department"] or user_info["department"].strip() == "":
        user_info["department"] = "unknown"
    
    if not user_info["email"] or user_info["email"].strip() == "":
        user_info["email"] = "system@aiops-platform.com"
    
    if not user_info["name"] or user_info["name"].strip() == "":
        user_info["name"] = "system"
    
    return user_info

def get_user_active_environment(user_obj, request_obj=None):
    if not user_obj:
        if request_obj and hasattr(request_obj, 'environment'):
            return getattr(request_obj, 'environment', 'dev').lower()
        return "dev"
    
    if request_obj and hasattr(request_obj, 'environment'):
        requested_env = getattr(request_obj, 'environment', 'dev').lower()
        if hasattr(user_obj, 'is_environment_active') and user_obj.is_environment_active(requested_env):
            logger.info(f"User {getattr(user_obj, 'email', 'unknown')} using requested environment: {requested_env}")
            return requested_env
    
    if hasattr(user_obj, 'is_environment_active'):
        env_priority = ["prod", "qa", "dev"]
        
        for env in env_priority:
            if user_obj.is_environment_active(env):
                logger.info(f"User {getattr(user_obj, 'email', 'unknown')} has active access to {env}")
                return env
        
        logger.warning(f"User {getattr(user_obj, 'email', 'unknown')} has no active environment access, defaulting to dev")
        return "dev"
    
    if request_obj and hasattr(request_obj, 'environment'):
        return getattr(request_obj, 'environment', 'dev').lower()
    
    return "dev"

def _parse_keypair_config(params: Dict[str, Any], user_info: Dict[str, str], request_identifier: str) -> Dict[str, Any]:
    # Initialize with None to detect if it was explicitly set
    keypair_config = {
        "key_name": "default",
        "create_new_keypair": None
    }
    
    logger.info(f"DEBUG: Raw params for keypair: {params}")
    
    # Check direct parameters first
    direct_key_name = params.get("key_name") or params.get("keyName")
    create_new = params.get("create_new_keypair")
    
    logger.info(f"DEBUG: direct_key_name={direct_key_name}, create_new={create_new}, type={type(create_new)}")
    
    if direct_key_name and direct_key_name.strip():
        keypair_config["key_name"] = direct_key_name.strip()
        # Handle boolean conversion properly - be more explicit
        if create_new in [True, "true", "True", 1, "1"]:
            keypair_config["create_new_keypair"] = True
        elif create_new in [False, "false", "False", 0, "0", None]:
            keypair_config["create_new_keypair"] = False
        else:
            # Default to False for any other value
            keypair_config["create_new_keypair"] = False
        logger.info(f"Using direct keypair config: {keypair_config} (create_new input was: {create_new}, type: {type(create_new)})")
        return keypair_config
    
    # Check nested keypair configuration
    key_pair = (
        params.get("key_pair") or 
        params.get("keypair") or 
        params.get("keyPair") or
        params.get("ssh_key") or
        {}
    )
    
    logger.info(f"Raw keypair config from params: {key_pair}")
    
    if isinstance(key_pair, dict):
        keypair_type = key_pair.get("type", "").lower()
        keypair_mode = key_pair.get("mode", "").lower()
        
        is_new_keypair = (
            keypair_type == "new" or
            keypair_mode == "new" or 
            key_pair.get("createNew", False) or
            key_pair.get("create_new", False)
        )
        
        if is_new_keypair:
            custom_name = (
                key_pair.get("name") or 
                key_pair.get("keyName") or 
                key_pair.get("keypair_name")
            )
            
            if custom_name and custom_name.strip():
                keypair_config["key_name"] = custom_name.strip()
            else:
                dept_clean = user_info["department"].lower().replace(" ", "-").replace("_", "-")
                # Add timestamp to avoid collisions
                import time
                timestamp = str(int(time.time()))[-6:]
                keypair_config["key_name"] = f"new-{dept_clean}-{timestamp}"
            
            keypair_config["create_new_keypair"] = True
            logger.info(f"New keypair will be created: {keypair_config['key_name']}")
            
        elif key_pair.get("name") or key_pair.get("keyName"):
            keypair_config["key_name"] = key_pair.get("name") or key_pair.get("keyName")
            keypair_config["create_new_keypair"] = False
            logger.info(f"Using existing keypair: {keypair_config['key_name']}")
            
    elif isinstance(key_pair, str) and key_pair.strip():
        if key_pair.lower() in ["new", "create"]:
            dept_clean = user_info["department"].lower().replace(" ", "-").replace("_", "-")
            # Add timestamp to avoid collisions
            import time
            timestamp = str(int(time.time()))[-6:]
            keypair_config["key_name"] = f"new-{dept_clean}-{timestamp}"
            keypair_config["create_new_keypair"] = True
        else:
            keypair_config["key_name"] = key_pair.strip()
            keypair_config["create_new_keypair"] = False
    
    # Set final default if not explicitly set - no auto generation
    if keypair_config["create_new_keypair"] is None:
        keypair_config["create_new_keypair"] = False
        if keypair_config["key_name"] == "default":
            keypair_config["key_name"] = "default-keypair"
    
    # FINAL FIX: Always respect direct parameter
    direct_create_new = params.get("create_new_keypair")
    if direct_create_new is not None:
        if direct_create_new in [True, "true", "True", 1, "1"]:
            keypair_config["create_new_keypair"] = True
            logger.info(f"FINAL FIX: Forcing create_new_keypair=True from direct parameter: {direct_create_new}")
        elif direct_create_new in [False, "false", "False", 0, "0"]:
            keypair_config["create_new_keypair"] = False
            logger.info(f"FINAL FIX: Setting create_new_keypair=False from direct parameter: {direct_create_new}")
    
    logger.info(f"Final keypair config: {keypair_config}")
    return keypair_config

def _render_tfvars_content(request_identifier: str, user: Optional[Any], params: Dict[str, Any], request_obj: Optional[Any] = None) -> str:
    """Generate tfvars using MCP service for ALL services"""
    resource_type = None
    
    request_lower = request_identifier.lower()
    if 's3_' in request_lower or request_lower.startswith('s3'):
        resource_type = "s3"
    elif 'lambda_' in request_lower or request_lower.startswith('lambda'):
        resource_type = "lambda"
    elif 'ec2_' in request_lower or request_lower.startswith('ec2'):
        resource_type = "ec2"
    
    if not resource_type:
        resource_type = params.get("resource_type") or getattr(request_obj, "resource_type", "ec2")
    
    logger.info(f"🔧 TFVARS RENDER: resource_type='{resource_type}' from request='{request_identifier}'")
    logger.info(f"🔧 TFVARS RENDER: Input params: {params}")
    
    # Use MCP service for ALL services
    try:
        import requests
        
        # Get user info
        user_info = _get_user_info(user, request_obj, params)
        
        # Prepare MCP payload
        mcp_payload = {
            "request_id": request_identifier,
            "service_type": resource_type,
            "parameters": {
                **params,
                "department": user_info["department"],
                "created_by": user_info["email"]
            }
        }
        
        logger.info(f"🔧 Calling MCP service for {resource_type}: {mcp_payload}")
        
        response = requests.post(
            "http://localhost:8001/mcp/generate-tfvars",
            json=mcp_payload,
            timeout=30.0
        )
        
        if response.status_code == 200:
            result = response.json()
            tfvars_content = result.get("tfvars_content")
            if tfvars_content:
                logger.info(f"✅ MCP generated {resource_type} tfvars successfully")
                return tfvars_content
            else:
                raise Exception("No tfvars_content in MCP response")
        else:
            raise Exception(f"MCP service error: HTTP {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"❌ MCP service failed for {resource_type}: {e}")
        logger.info(f"🔄 Falling back to local generation for {resource_type}")
        
        # Fallback to local generation
        if resource_type == "s3":
            return _render_s3_tfvars(request_identifier, user, params, request_obj)
        elif resource_type == "lambda":
            return _render_lambda_tfvars(request_identifier, user, params, request_obj)
        else:
            return _render_ec2_tfvars(request_identifier, user, params, request_obj)

def _render_s3_tfvars(request_identifier: str, user: Optional[Any], params: Dict[str, Any], request_obj: Optional[Any] = None) -> str:
    user_info = _get_user_info(user, request_obj, params)
    
    requested_env = params.get("environment") or params.get("env")
    if requested_env:
        environment = requested_env.lower()
    else:
        environment = get_user_active_environment(user, request_obj)
    
    logger.info(f"S3 tfvars - params: {params}")
    
    # PRESERVE USER VALUES - no defaults
    if not params.get("bucket_name"):
        raise ValueError("bucket_name is required for S3")
    
    # Validate bucket name format
    bucket_name = params.get("bucket_name")
    if not bucket_name or len(bucket_name) < 3 or len(bucket_name) > 63:
        raise ValueError("S3 bucket name must be 3-63 characters long")
    
    tfvars = {
        "bucket_name": params.get("bucket_name"),  # USER VALUE REQUIRED
        "aws_region": params.get("aws_region") or params.get("region") or os.getenv('AWS_DEFAULT_REGION') or "us-east-1",
        "versioning_enabled": params.get("versioning_enabled", False),
        "block_public_access": params.get("block_public_access", True)
    }
    

    
    lines = []
    for k, v in tfvars.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f'{k} = {str(v).lower()}')
        elif isinstance(v, (int, float)):
            lines.append(f'{k} = {v}')
    
    logger.info(f"Generated S3 tfvars: {lines}")
    return '\n'.join(lines) + '\n'

def _render_lambda_tfvars(request_identifier: str, user: Optional[Any], params: Dict[str, Any], request_obj: Optional[Any] = None) -> str:
    user_info = _get_user_info(user, request_obj, params)
    
    requested_env = params.get("environment") or params.get("env")
    if requested_env:
        environment = requested_env.lower()
    else:
        environment = get_user_active_environment(user, request_obj)
    
    logger.info(f"Lambda tfvars - params: {params}")
    
    runtime = params.get("runtime", "python3.9")
    if "python" in runtime:
        default_code = "def lambda_handler(event, context):\n    return {'statusCode': 200, 'body': 'Hello from Lambda!'}"
        default_handler = "index.lambda_handler"
    else:
        default_code = "exports.handler = async (event) => { return { statusCode: 200, body: 'Hello from Lambda!' }; };"
        default_handler = "index.handler"
    
    # PRESERVE USER VALUES - no defaults
    function_name = params.get("lambda_function_name") or params.get("function_name")
    if not function_name:
        raise ValueError("lambda_function_name is required for Lambda")
    
    # Validate function name format
    if not function_name or len(function_name) < 1 or len(function_name) > 64:
        raise ValueError("Lambda function name must be 1-64 characters long")
    
    tfvars = {
        "lambda_function_name": params.get("lambda_function_name") or params.get("function_name"),  # USER VALUE REQUIRED
        "lambda_runtime": params.get("lambda_runtime") or params.get("runtime", "python3.12"),
        "lambda_handler": params.get("lambda_handler") or params.get("handler", default_handler),
        "lambda_timeout": params.get("lambda_timeout") or params.get("timeout", 30),
        "lambda_memory_size": params.get("lambda_memory_size") or params.get("memory_size", 128),
        "aws_region": params.get("aws_region") or params.get("region") or os.getenv('AWS_DEFAULT_REGION') or "us-east-1"
    }
    

    
    lines = []
    for k, v in tfvars.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, (int, float)):
            lines.append(f'{k} = {v}')
    
    logger.info(f"Generated Lambda tfvars: {lines}")
    return '\n'.join(lines) + '\n'

def _render_ec2_tfvars(request_identifier: str, user: Optional[Any], params: Dict[str, Any], request_obj: Optional[Any] = None) -> str:
    """Generate EC2 tfvars - PRESERVE USER CHOICES, NO FALLBACK OVERRIDES"""
    
    user_info = _get_user_info(user, request_obj, params)
    
    # Get user's exact choices - NO DEFAULTS
    os_type = params.get("operating_system") or params.get("os")
    if not os_type:
        raise ValueError("operating_system is required")
    
    os_type = os_type.lower().strip()
    
    # Parse storage size
    storage_raw = params.get("storage_size", 8)
    if isinstance(storage_raw, str):
        storage_clean = storage_raw.replace("GB", "").replace("gb", "").strip()
        try:
            storage_size = int(storage_clean)
        except ValueError:
            storage_size = 8
    else:
        storage_size = storage_raw
    
    # Build basic tfvars with user's exact choices
    tfvars = {
        "request_id": request_identifier,
        "department": user_info["department"],
        "created_by": user_info["email"],
        "environment": params.get("environment", "dev"),
        "operating_system": os_type,  # PRESERVE user choice
        "instance_type": params.get("instance_type", "t3.micro"),
        "storage_size": storage_size,
        "region": params.get("region") or os.getenv('AWS_DEFAULT_REGION') or "us-east-1"
    }
    
    logger.info(f"🔧 EC2 tfvars: User requested OS='{os_type}', region='{tfvars['region']}'")
    
    # CRITICAL: Preserve user's OS choice and get dynamic AMI filter via MCP
    tfvars["operating_system"] = os_type  # ALWAYS preserve user choice
    
    # Get dynamic AMI filter via MCP service - NO HARDCODED AMI IDs
    try:
        import requests
        
        # First validate OS in region
        validation_response = requests.post(
            "http://localhost:8001/mcp/validate-os-region",
            json={
                "operating_system": os_type,
                "region": tfvars["region"]
            },
            timeout=10.0
        )
        
        if validation_response.status_code != 200:
            raise Exception(f"OS validation service unavailable: {validation_response.status_code}")
        
        validation_data = validation_response.json()
        
        if not validation_data.get("valid"):
            # OS not supported in this region - show available options
            available_os = validation_data.get("available_os", [])
            suggestion = validation_data.get("suggestion", "")
            error_msg = f"❌ {os_type} is not available in {tfvars['region']}. Available: {', '.join(available_os)}. {suggestion}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # OS is valid, get dynamic AMI filter (NOT AMI ID)
        os_filters_response = requests.post(
            "http://localhost:8001/mcp/get-os-filters",
            json={
                "operating_system": os_type
            },
            timeout=10.0
        )
        
        if os_filters_response.status_code != 200:
            raise Exception(f"OS filters service unavailable: {os_filters_response.status_code}")
        
        filters_data = os_filters_response.json()
        
        if not filters_data.get("supported"):
            raise Exception(f"OS filters not found for {os_type}")
        
        # SUCCESS: Use dynamic AMI filter from MCP (Terraform will find latest AMI)
        tfvars["ami_filter"] = filters_data.get("ami_filter")
        tfvars["ami_owners"] = filters_data.get("ami_owners", ["099720109477"])
        tfvars["os_display_name"] = filters_data.get("display_name", os_type)
        
        logger.info(f"✅ MCP: Dynamic AMI filter for {filters_data.get('display_name')}: {filters_data.get('ami_filter')}")
        logger.info(f"✅ Terraform will find LATEST AMI using this filter at deployment time")
        
    except Exception as e:
        logger.error(f"❌ MCP service error: {e}")
        raise ValueError(f"Cannot get AMI filter for {os_type} in {tfvars['region']}: {str(e)}")
    
    # Determine associate_public_ip based on subnet type
    subnet_config = params.get("subnet") or {}
    subnet_type = subnet_config.get("type", "public")  # From LLM processor
    
    # Logic: public subnet = true, private subnet = false
    associate_public_ip = subnet_type == "public"
    tfvars["associate_public_ip"] = associate_public_ip

    # Handle keypair configuration properly
    keypair_config = _parse_keypair_config(params, user_info, request_identifier)
    tfvars["key_name"] = keypair_config["key_name"]
    tfvars["create_new_keypair"] = keypair_config["create_new_keypair"]
    
    # Ensure keypair name is valid when creating new
    if keypair_config["create_new_keypair"] and not keypair_config["key_name"]:
        tfvars["key_name"] = "new-keypair"
    
    # Handle None case - default to False (no auto generation)
    if tfvars["create_new_keypair"] is None:
        tfvars["create_new_keypair"] = False
    
    # FINAL OVERRIDE: Ensure create_new_keypair is set correctly
    direct_param = params.get("create_new_keypair")
    if direct_param in [True, "true", "True", 1, "1"]:
        tfvars["create_new_keypair"] = True
        logger.info(f"FINAL OVERRIDE: Set create_new_keypair=True from param: {direct_param}")
    elif direct_param in [False, "false", "False", 0, "0"]:
        tfvars["create_new_keypair"] = False
        logger.info(f"FINAL OVERRIDE: Set create_new_keypair=False from param: {direct_param}")
    
    logger.info(f"Final keypair settings: key_name={tfvars['key_name']}, create_new_keypair={tfvars['create_new_keypair']}")
    logger.info(f"Original create_new_keypair param: {params.get('create_new_keypair')} (type: {type(params.get('create_new_keypair'))})")

    vpc = params.get("vpc") or {}
    if vpc.get("mode") == "existing" and vpc.get("id"):
        tfvars["vpc_id"] = vpc.get("id")
        tfvars["use_existing_vpc"] = True
    else:
        tfvars["vpc_id"] = ""
        tfvars["use_existing_vpc"] = False

    subnet = params.get("subnet") or {}
    if subnet.get("mode") == "existing" and subnet.get("id"):
        tfvars["subnet_id"] = subnet.get("id")
        tfvars["use_existing_subnet"] = True
    else:
        tfvars["subnet_id"] = ""
        tfvars["use_existing_subnet"] = False

    security_group = params.get("security_group") or {}
    if security_group.get("mode") == "existing" and security_group.get("id"):
        tfvars["security_group_id"] = security_group.get("id")
        tfvars["use_existing_sg"] = True
    else:
        tfvars["security_group_id"] = ""
        tfvars["use_existing_sg"] = False

    # Instance tags
    name_clean = user_info["name"].replace(" ", "-").replace(".", "-").lower()
    tfvars["instance_tags"] = {
        "Name": f"{name_clean}-ec2-{request_identifier.split('_')[-1]}",
        "Department": user_info["department"],
        "Environment": tfvars["environment"],
        "RequestID": request_identifier,
        "CreatedBy": user_info["email"],
        "ManagedBy": "AIOps-Platform"
    }
    
    # CRITICAL VALIDATION: Ensure user's choice is preserved
    if tfvars["operating_system"] != os_type:
        logger.error(f"🚨 CRITICAL ERROR: User requested '{os_type}' but tfvars has '{tfvars['operating_system']}'")
        raise ValueError(f"User choice not preserved: requested '{os_type}' but got '{tfvars['operating_system']}'")
    
    # Ensure AMI filter is present (Terraform will find latest AMI)
    if not tfvars.get("ami_filter"):
        raise ValueError(f"No AMI filter found for {os_type}")
    
    return _generate_ec2_tfvars_content(tfvars)



def _generate_ec2_tfvars_content(tfvars: Dict[str, Any]) -> str:
    """Generate EC2 tfvars content from tfvars dict"""
    lines = []
    
    # Add comments
    if tfvars.get("ami_filter"):
        lines.append(f"# AMI Filter: {tfvars['ami_filter']}")
    if tfvars.get("os_display_name"):
        lines.append(f"# Operating System: {tfvars['os_display_name']}")
    lines.append(f"# Terraform will find LATEST AMI using the filter above")
    
    # Only include terraform variables (no metadata)
    terraform_vars = [
        "operating_system", "instance_type", "storage_size", "region",
        "ami_filter", "ami_owners", "key_name", "create_new_keypair", 
        "vpc_id", "use_existing_vpc", "subnet_id", "use_existing_subnet", 
        "security_group_id", "use_existing_sg", "associate_public_ip"
    ]
    
    # Add terraform variables only
    for k in terraform_vars:
        if k in tfvars:
            v = tfvars[k]
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {str(v).lower()}')
            elif isinstance(v, (int, float)):
                lines.append(f'{k} = {v}')
            elif isinstance(v, list):
                items = ', '.join([f'"{i}"' for i in v])
                lines.append(f'{k} = [{items}]')
    
    # Add instance_tags separately
    if "instance_tags" in tfvars:
        tag_lines = []
        for tag_k, tag_v in tfvars["instance_tags"].items():
            tag_lines.append(f'  "{tag_k}" = "{tag_v}"')
        lines.append(f'instance_tags = {{\n{chr(10).join(tag_lines)}\n}}')
    
    logger.info(f"✅ Generated EC2 tfvars: OS='{tfvars['operating_system']}', AMI_Filter='{tfvars.get('ami_filter', 'N/A')}'")
    logger.info(f"TFVARS CONTENT:\n{chr(10).join(lines)}")
    
    return '\n'.join(lines) + '\n'

class TerraformManager:
    async def deploy_infrastructure(
        self,
        service_type: str,
        config: Dict[str, Any],
        user_info: Dict[str, str],
        db: Any
    ) -> Dict[str, Any]:
        """Deploy infrastructure by creating DB record and triggering Celery task"""
        try:
            from .models import InfrastructureRequest
            from .tasks import process_infrastructure_request
            import uuid
            from datetime import datetime
            
            request_id = f"{service_type}_{user_info.get('department', 'unknown')}_{int(datetime.now().timestamp())}"
            
            logger.info(f"🚀 DEPLOY: service_type='{service_type}', request_id='{request_id}'")
            logger.info(f"🚀 DEPLOY: config={config}")
            
            user_id = user_info.get("user_id")
            if user_id and isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    logger.error(f"Invalid UUID format: {user_id}")
                    user_id = None
            
            if not user_id:
                from .models import User
                from sqlalchemy import select
                result = await db.execute(
                    select(User).where(User.email == user_info.get("email"))
                )
                existing_user = result.scalar_one_or_none()
                if existing_user:
                    user_id = existing_user.id
                    logger.info(f"Found user by email: {existing_user.email}")
                else:
                    logger.error(f"User not found: {user_info.get('email')}")
                    return {
                        "success": False,
                        "message": "User not found in database"
                    }
            
            config_with_type = config.copy()
            config_with_type["resource_type"] = service_type
            
            infra_request = InfrastructureRequest(
                request_identifier=request_id,
                user_id=user_id,
                cloud_provider="aws",
                resource_type=service_type,
                environment=config.get("environment", "dev"),
                status="pending",
                request_parameters=config_with_type
            )
            
            db.add(infra_request)
            await db.commit()
            await db.refresh(infra_request)
            
            logger.info(f"✅ Created infrastructure request: {request_id} with resource_type: {service_type}")
            
            try:
                task = process_infrastructure_request.delay(request_id, user_info.get("email"))
                logger.info(f"✅ Triggered Celery task: {task.id} for {request_id}")
                
                return {
                    "success": True,
                    "request_id": request_id,
                    "task_id": task.id,
                    "message": "Request submitted for approval successfully"
                }
            except Exception as celery_error:
                logger.error(f"❌ Celery task failed: {celery_error}")
                infra_request.status = "failed"
                db.commit()
                
                return {
                    "success": False,
                    "request_id": request_id,
                    "message": f"Failed to start deployment: {celery_error}"
                }
                
        except Exception as e:
            logger.error(f"❌ Deploy infrastructure failed: {e}")
            return {
                "success": False,
                "message": f"Deployment failed: {e}"
            }
    
    async def generate_tfvars_for_request(
        self,
        request_identifier: str,
        params: Dict[str, Any] = None,
        user: Optional[Any] = None,
        request_obj: Optional[Any] = None,
        repo_root_override: Optional[str] = None,
    ) -> Tuple[Path, Optional[Path]]:
        if not params and request_obj:
            if isinstance(request_obj, dict):
                params = request_obj.get("request_parameters", {})
            else:
                params = getattr(request_obj, "request_parameters", {})
        params = params or {}
        if repo_root_override:
            repo_root = Path(repo_root_override).expanduser().resolve()
        else:
            repo_root = find_repo_root() or Path.cwd().resolve()

        logger.info("TerraformManager: using repo_root=%s", repo_root)

        cloud_provider = "aws"
        if request_obj:
            if isinstance(request_obj, dict):
                cloud_provider = request_obj.get("cloud_provider", "aws")
            else:
                cloud_provider = getattr(request_obj, "cloud_provider", "aws")
        cloud = (params.get("cloud") or params.get("cloud_provider") or cloud_provider).lower()
        
        environment = get_user_active_environment(user, request_obj)
        
        if params.get("environment"):
            requested = params.get("environment").lower()
            if user and hasattr(user, 'is_environment_active') and user.is_environment_active(requested):
                environment = requested
                logger.info(f"Using explicitly requested environment: {requested}")
            else:
                logger.warning(f"User doesn't have access to {requested}, using {environment}")

        logger.info(f"TerraformManager: using environment={environment} for request={request_identifier}")

        requests_dir = repo_root / "terraform" / "environments" / cloud / environment / "requests"
        _ensure_dir(requests_dir)

        tfvars_path = requests_dir / f"{request_identifier}.tfvars"
        content = _render_tfvars_content(request_identifier, user, params, request_obj)

        tmp = tfvars_path.with_suffix(".tfvars.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(tfvars_path)

        logger.info("TerraformManager: generated tfvars file: %s", tfvars_path)

        clone_expected = Path("terraform") / "environments" / cloud / environment / "requests" / f"{request_identifier}.tfvars"
        return tfvars_path, clone_expected

def generate_tfvars_for_request_sync(request_identifier: str, params: Dict[str, Any] = None, user: Optional[Any] = None, request_obj: Optional[Any] = None, repo_root_override: Optional[str] = None):
    return asyncio.get_event_loop().run_until_complete(
        TerraformManager().generate_tfvars_for_request(request_identifier, params, user, request_obj, repo_root_override)
    )