# backend/mcp_service/app.py
import os
import re
import json
import httpx
import boto3
import logging
from functools import lru_cache
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Validate AWS credentials
def validate_aws_credentials():
    """Validate AWS credentials and return status"""
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    if not aws_access_key or not aws_secret_key:
        return False, "AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY not set"
    
    if aws_access_key == "your_aws_access_key_here" or aws_secret_key == "your_aws_secret_key_here":
        return False, "Please set real AWS credentials in .env file"
    
    try:
        # Test credentials with STS
        sts_client = boto3.client(
            'sts',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name='us-east-1'
        )
        sts_client.get_caller_identity()
        return True, "AWS credentials valid"
    except Exception as e:
        return False, f"AWS credentials invalid: {str(e)}"

# Check AWS credentials
AWS_AVAILABLE, aws_status = validate_aws_credentials()

if AWS_AVAILABLE:
    try:
        # Initialize AWS clients with validated credentials
        pricing_client = boto3.client(
            "pricing", 
            region_name="us-east-1",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        ec2_client = boto3.client(
            "ec2", 
            region_name="us-east-1",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        logger.info(f"✅ AWS clients initialized: {aws_status}")
    except Exception as e:
        logger.error(f"❌ AWS client initialization failed: {e}")
        AWS_AVAILABLE = False
        pricing_client = None
        ec2_client = None
else:
    logger.error(f"❌ AWS not available: {aws_status}")
    pricing_client = None
    ec2_client = None

app = FastAPI(title="MCP Service")

@app.get("/")
async def root():
    return {
        "message": "MCP Service Running",
        "aws_available": AWS_AVAILABLE,
        "aws_status": aws_status,
        "endpoints": [
            "/mcp/validate-os-region",
            "/mcp/get-os-filters", 
            "/mcp/get-ami-details",
            "/mcp/get-hourly-cost",
            "/mcp/calculate-cost",
            "/mcp/get-s3-cost",
            "/mcp/get-lambda-cost",
            "/mcp/generate-tfvars",
            "/mcp/health"
        ]
    }

@app.get("/mcp/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "mcp",
        "aws_available": AWS_AVAILABLE,
        "aws_status": aws_status
    }

@app.post("/mcp/validate-os-region")
async def validate_os_region_endpoint(request: dict = Body(...)):
    """Validate if OS is supported in the given region"""
    if not AWS_AVAILABLE:
        return {
            "valid": False,
            "error": "aws_unavailable",
            "message": f"AWS not available: {aws_status}",
            "suggestion": "Please configure valid AWS credentials in .env file"
        }
    
    try:
        os_type = request.get("operating_system", "").lower().strip()
        region = request.get("region", "us-east-1")
        
        if not os_type:
            return {
                "valid": False,
                "error": "missing_os",
                "message": "Operating system is required"
            }
        
        # Get AMI details to validate
        ami_response = await get_ami_details_endpoint({"operating_system": os_type, "region": region})
        
        if ami_response.get("ami_id") and ami_response.get("supported"):
            return {
                "valid": True,
                "operating_system": os_type,
                "region": region,
                "ami_id": ami_response.get("ami_id"),
                "message": f"{os_type} is supported in {region}"
            }
        else:
            return {
                "valid": False,
                "operating_system": os_type,
                "region": region,
                "error": "os_not_supported",
                "message": f"{os_type} is not available in {region}",
                "suggestion": "Check available OS types for this region"
            }
            
    except Exception as e:
        logger.error(f"OS validation error: {e}")
        return {
            "valid": False,
            "error": "validation_error",
            "message": str(e)
        }

@app.post("/mcp/get-os-filters")
async def get_os_filters_endpoint(request: dict = Body(...)):
    """Get OS AMI filters dynamically"""
    if not AWS_AVAILABLE:
        return {
            "supported": False,
            "error": "aws_unavailable",
            "message": f"AWS not available: {aws_status}"
        }
    
    try:
        os_type = request.get("operating_system", "").lower().strip()
        
        # Dynamic OS filter mapping - LATEST versions
        os_config = {
            "ubuntu": {
                "ami_filter": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
                "ami_owners": ["099720109477"],
                "display_name": "Ubuntu 22.04 LTS (Latest)"
            },
            "amazon-linux": {
                "ami_filter": "al2023-ami-*-x86_64",
                "ami_owners": ["137112412989"],
                "display_name": "Amazon Linux 2023 (Latest)"
            },
            "windows": {
                "ami_filter": "Windows_Server-2022-English-Full-Base-*",
                "ami_owners": ["801119661308"],
                "display_name": "Windows Server 2022 (Latest)"
            }
        }
        
        if os_type in os_config:
            config = os_config[os_type]
            return {
                "operating_system": os_type,
                "ami_filter": config["ami_filter"],
                "ami_owners": config["ami_owners"],
                "display_name": config["display_name"],
                "supported": True,
                "source": "dynamic_config"
            }
        else:
            return {
                "supported": False,
                "error": "unsupported_os",
                "message": f"OS '{os_type}' not supported",
                "supported_os": list(os_config.keys())
            }
            
    except Exception as e:
        logger.error(f"OS filters error: {e}")
        return {
            "supported": False,
            "error": "os_filters_error",
            "message": str(e)
        }

@app.post("/mcp/get-ami-details")
async def get_ami_details_endpoint(request: dict = Body(...)):
    """Get AMI details - STRICT OS matching to prevent wrong selections"""
    if not AWS_AVAILABLE:
        return {
            "supported": False,
            "error": "aws_unavailable",
            "message": f"AWS not available: {aws_status}"
        }
    
    try:
        os_type = request.get("operating_system", "ubuntu").lower().strip()
        region = request.get("region", "us-east-1")
        
        logger.info(f"STRICT AMI search for OS: {os_type} in region: {region}")
        
        ec2_regional = boto3.client(
            "ec2", 
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        
        # STRICT OS-specific AMI filters - NO cross-contamination
        os_search_config = {
            "ubuntu": {
                "owners": ["099720109477"],  # Canonical
                "name_patterns": ["ubuntu/images/hvm-ssd/ubuntu-*", "ubuntu*server*", "ubuntu/images*server*"],
                "required_keywords": ["ubuntu"],
                "excluded_keywords": ["centos", "rhel", "windows"]
            },
            "amazon-linux": {
                "owners": ["137112412989"],  # Amazon
                "name_patterns": ["amzn2-ami-hvm-*", "al2023-ami-*"],
                "required_keywords": ["amzn", "amazon"],
                "excluded_keywords": ["ubuntu", "centos", "rhel", "windows"]
            },
            "windows": {
                "owners": ["801119661308"],  # Amazon
                "name_patterns": ["Windows_Server-*"],
                "required_keywords": ["windows"],
                "excluded_keywords": ["linux", "ubuntu", "centos", "rhel"]
            }
        }
        
        if os_type not in os_search_config:
            return {
                "error": "unsupported_os",
                "message": f"OS '{os_type}' not supported",
                "supported_os": list(os_search_config.keys())
            }
        
        config = os_search_config[os_type]
        
        # Search with STRICT filters
        for pattern in config["name_patterns"]:
            try:
                response = ec2_regional.describe_images(
                    Owners=config["owners"],
                    Filters=[
                        {"Name": "name", "Values": [pattern]},
                        {"Name": "state", "Values": ["available"]},
                        {"Name": "architecture", "Values": ["x86_64"]}
                    ],
                    MaxResults=50
                )
                
                if response["Images"]:
                    # STRICT validation - must contain required keywords, must NOT contain excluded
                    valid_amis = []
                    for ami in response["Images"]:
                        ami_name = ami["Name"].lower()
                        
                        # Check required keywords
                        has_required = any(keyword in ami_name for keyword in config["required_keywords"])
                        # Check excluded keywords
                        has_excluded = any(keyword in ami_name for keyword in config["excluded_keywords"])
                        
                        if has_required and not has_excluded:
                            valid_amis.append(ami)
                    
                    if valid_amis:
                        # Get latest AMI
                        latest_ami = sorted(valid_amis, key=lambda x: x["CreationDate"], reverse=True)[0]
                        
                        return {
                            "operating_system": os_type,
                            "display_name": os_type.replace("-", " ").title(),
                            "region": region,
                            "ami_id": latest_ami["ImageId"],
                            "ami_name": latest_ami["Name"],
                            "creation_date": latest_ami["CreationDate"],
                            "owner_id": latest_ami["OwnerId"],
                            "supported": True
                        }
                        
            except Exception as e:
                logger.warning(f"Pattern {pattern} failed: {e}")
                continue
        
        # No AMI found
        return {
            "error": "no_ami_found",
            "message": f"No {os_type} AMI found in {region}",
            "operating_system": os_type
        }
        
    except Exception as e:
        logger.error(f"AMI search error: {e}")
        return {
            "error": "service_error",
            "message": str(e),
            "operating_system": os_type
        }

@app.post("/mcp/get-hourly-cost")
async def get_hourly_cost_endpoint(request: dict = Body(...)):
    """Get real-time hourly cost for instance type in region"""
    if not AWS_AVAILABLE:
        return {
            "error": "aws_unavailable",
            "message": f"AWS not available: {aws_status}"
        }
    
    try:
        instance_type = request.get("instance_type", "t3.micro")
        region = request.get("region", "us-east-1")
        os_type = request.get("operating_system", "linux").lower()
        
        # Map OS types
        os_map = {"ubuntu": "Linux", "amazon-linux": "Linux", "linux": "Linux", "windows": "Windows"}
        operating_system = os_map.get(os_type, "Linux")
        
        # Get real AWS pricing
        hourly_cost = get_instance_hourly_price(instance_type, region, os_type)
        
        return {
            "instance_type": instance_type,
            "region": region,
            "operating_system": os_type,
            "hourly_cost": round(hourly_cost, 4),
            "daily_cost": round(hourly_cost * 24, 2),
            "monthly_cost": round(hourly_cost * 24 * 30, 2),
            "currency": "USD",
            "source": "aws_pricing_api_realtime"
        }
        
    except Exception as e:
        logger.error(f"Cost calculation error: {e}")
        return {
            "error": "cost_error",
            "message": str(e),
            "instance_type": request.get("instance_type", "t3.micro"),
            "region": request.get("region", "us-east-1")
        }

@app.post("/mcp/get-s3-cost")
async def get_s3_cost_endpoint(request: dict = Body(...)):
    """Get S3 storage cost estimation"""
    try:
        region = request.get("region", "us-east-1")
        storage_gb = request.get("storage_gb", 1)
        storage_class = request.get("storage_class", "STANDARD")
        
        # S3 pricing per GB per month (approximate)
        s3_pricing = {
            "us-east-1": {"STANDARD": 0.023, "IA": 0.0125, "GLACIER": 0.004},
            "us-west-2": {"STANDARD": 0.023, "IA": 0.0125, "GLACIER": 0.004},
            "ap-south-1": {"STANDARD": 0.025, "IA": 0.014, "GLACIER": 0.005},
            "eu-west-1": {"STANDARD": 0.024, "IA": 0.013, "GLACIER": 0.0045}
        }
        
        price_per_gb = s3_pricing.get(region, s3_pricing["us-east-1"]).get(storage_class, 0.023)
        monthly_cost = storage_gb * price_per_gb
        
        return {
            "service": "s3",
            "region": region,
            "storage_gb": storage_gb,
            "storage_class": storage_class,
            "monthly_cost": round(monthly_cost, 4),
            "currency": "USD",
            "source": "aws_s3_pricing"
        }
        
    except Exception as e:
        logger.error(f"S3 cost calculation error: {e}")
        return {"error": "s3_cost_error", "message": str(e)}

@app.post("/mcp/get-lambda-cost")
async def get_lambda_cost_endpoint(request: dict = Body(...)):
    """Get Lambda function cost estimation"""
    try:
        region = request.get("region", "us-east-1")
        memory_mb = request.get("memory_mb", 128)
        monthly_requests = request.get("monthly_requests", 1000)
        avg_duration_ms = request.get("avg_duration_ms", 1000)
        
        # Lambda pricing (approximate)
        request_price = 0.0000002  # per request
        gb_second_price = 0.0000166667  # per GB-second
        
        # Calculate costs
        request_cost = monthly_requests * request_price
        
        # Convert memory to GB and duration to seconds
        memory_gb = memory_mb / 1024
        duration_seconds = avg_duration_ms / 1000
        
        compute_cost = monthly_requests * memory_gb * duration_seconds * gb_second_price
        total_monthly = request_cost + compute_cost
        
        return {
            "service": "lambda",
            "region": region,
            "memory_mb": memory_mb,
            "monthly_requests": monthly_requests,
            "avg_duration_ms": avg_duration_ms,
            "monthly_cost": round(total_monthly, 6),
            "breakdown": {
                "request_cost": round(request_cost, 6),
                "compute_cost": round(compute_cost, 6)
            },
            "currency": "USD",
            "source": "aws_lambda_pricing"
        }
        
    except Exception as e:
        logger.error(f"Lambda cost calculation error: {e}")
        return {"error": "lambda_cost_error", "message": str(e)}

@app.post("/mcp/calculate-cost")
async def calculate_cost_endpoint(request: dict = Body(...)):
    """Calculate EC2 cost with proper hourly calculation - NO per-minute increases"""
    if not AWS_AVAILABLE:
        return {
            "error": "aws_unavailable",
            "message": f"AWS not available: {aws_status}"
        }
    
    try:
        instance_type = request.get("instance_type", "t3.micro")
        region = request.get("region", "us-east-1")
        os_type = request.get("operating_system", "ubuntu").lower()
        storage_size = request.get("storage_size", 8)
        
        # Get HOURLY cost from AWS Pricing API
        hourly_instance_cost = get_instance_hourly_price(instance_type, region, os_type)
        
        # EBS storage cost (per GB per month)
        storage_monthly_cost = storage_size * 0.10  # $0.10 per GB per month for gp3
        
        # Calculate monthly costs (30 days * 24 hours)
        monthly_instance_cost = hourly_instance_cost * 24 * 30
        total_monthly_cost = monthly_instance_cost + storage_monthly_cost
        
        return {
            "instance_type": instance_type,
            "region": region,
            "operating_system": os_type,
            "storage_size": storage_size,
            "hourly_cost": round(hourly_instance_cost, 4),
            "monthly_cost": round(total_monthly_cost, 2),
            "breakdown": {
                "instance_monthly": round(monthly_instance_cost, 2),
                "storage_monthly": round(storage_monthly_cost, 2)
            },
            "currency": "USD",
            "calculation_method": "hourly_rate_x_720_hours",
            "source": "aws_pricing_api"
        }
        
    except Exception as e:
        logger.error(f"Cost calculation error: {e}")
        return {
            "error": "cost_calculation_failed",
            "message": str(e)
        }

@app.post("/mcp/generate-tfvars")
async def generate_tfvars_endpoint(data: dict = Body(...)):
    """Generate tfvars content for EC2 deployment - NO HARDCODED AMI IDs"""
    try:
        request_id = data["request_id"]
        params = data["parameters"]
        service_type = data.get("service_type", "ec2")
        
        # Extract user info
        department = params.get("department", "Unknown")
        created_by = params.get("created_by", "system@aiops.com")
        environment = params.get("environment", "dev")
        
        # Generate name from email
        name_clean = created_by.split("@")[0].replace(".", "-").lower()
        
        if service_type == "ec2":
            os_type = params.get("operating_system", "ubuntu").lower()
            region = params.get("region", "us-east-1")
            
            # VALIDATE OS/REGION FIRST
            validation_response = await validate_os_region_endpoint({"operating_system": os_type, "region": region})
            if not validation_response.get("valid"):
                raise HTTPException(status_code=400, detail=f"OS validation failed: {validation_response.get('message')}")
            
            # Get OS filters - Terraform will find latest AMI at deployment time
            os_response = await get_os_filters_endpoint({"operating_system": os_type})
            if not os_response.get("supported"):
                raise HTTPException(status_code=400, detail=f"OS filters not found for {os_type}")
            
            ami_filter = os_response.get("ami_filter")
            ami_owners = os_response.get("ami_owners", ["099720109477"])
            
            # NO AMI ID - Terraform will find latest using filter
            tfvars_content = f'''# AMI Filter: {ami_filter}
# Operating System: {os_response.get('display_name', os_type)}
# Terraform will find LATEST AMI using the filter above
request_id = "{request_id}"
department = "{department}"
created_by = "{created_by}"
environment = "{environment}"
instance_type = "{params.get('instance_type', 't3.micro')}"
storage_size = {params.get('storage_size', 8)}
region = "{region}"
operating_system = "{os_type}"
ami_filter = "{ami_filter}"
ami_owners = {json.dumps(ami_owners)}
associate_public_ip = {str(params.get('associate_public_ip', True)).lower()}
key_name = "{params.get('key_name', f'{name_clean}-keypair')}"
create_new_keypair = {str(params.get('create_new_keypair', True)).lower()}
vpc_id = "{params.get('vpc', {}).get('id', '')}"
use_existing_vpc = {str(bool(params.get('vpc', {}).get('id'))).lower()}
subnet_id = "{params.get('subnet', {}).get('id', '')}"
use_existing_subnet = {str(bool(params.get('subnet', {}).get('id'))).lower()}
security_group_id = "{params.get('security_group', {}).get('id', '')}"
use_existing_sg = {str(bool(params.get('security_group', {}).get('id'))).lower()}
instance_tags = {{
  "Name" = "{name_clean}-ec2-{request_id.split('_')[-1]}"
  "Department" = "{department}"
  "Environment" = "{environment}"
  "RequestID" = "{request_id}"
  "CreatedBy" = "{created_by}"
  "ManagedBy" = "AIOps-Platform"
  "OS" = "{os_type}"
}}'''
        
        elif service_type == "s3":
            bucket_name = params.get("bucket_name")
            if not bucket_name:
                raise HTTPException(status_code=400, detail="bucket_name is required for S3")
            
            region = params.get("aws_region", params.get("region", "us-east-1"))
            
            tfvars_content = f'''# S3 Bucket Configuration
request_id = "{request_id}"
department = "{department}"
created_by = "{created_by}"
environment = "{environment}"
bucket_name = "{bucket_name}"
aws_region = "{region}"
versioning_enabled = {str(params.get('versioning_enabled', False)).lower()}
block_public_access = {str(params.get('block_public_access', True)).lower()}
encryption_enabled = {str(params.get('encryption_enabled', True)).lower()}'''
        
        elif service_type == "lambda":
            function_name = params.get("lambda_function_name")
            if not function_name:
                raise HTTPException(status_code=400, detail="lambda_function_name is required for Lambda")
            
            region = params.get("aws_region", params.get("region", "us-east-1"))
            runtime = params.get("lambda_runtime", "python3.12")
            
            tfvars_content = f'''# Lambda Function Configuration
request_id = "{request_id}"
department = "{department}"
created_by = "{created_by}"
environment = "{environment}"
lambda_function_name = "{function_name}"
lambda_runtime = "{runtime}"
lambda_handler = "{params.get('lambda_handler', 'index.lambda_handler')}"
lambda_timeout = {params.get('lambda_timeout', 30)}
lambda_memory_size = {params.get('lambda_memory_size', 128)}
aws_region = "{region}"'''
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported service type: {service_type}. Supported: ec2, s3, lambda")
        
        result = {
            "status": "success",
            "tfvars_content": tfvars_content,
            "request_id": request_id,
            "service_type": service_type
        }
        
        # Add service-specific metadata
        if service_type == "ec2":
            result["ami_filter"] = ami_filter
            result["os_validated"] = True
            result["note"] = "Terraform will find latest AMI using ami_filter at deployment time"
        elif service_type == "s3":
            result["bucket_name"] = params.get("bucket_name")
            result["note"] = "S3 bucket will be created with specified configuration"
        elif service_type == "lambda":
            result["function_name"] = params.get("lambda_function_name")
            result["note"] = "Lambda function will be created with specified configuration"
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating tfvars: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate tfvars: {str(e)}")

@lru_cache(maxsize=200)
def get_instance_hourly_price(instance_type: str, region: str, os: str) -> float:
    if not AWS_AVAILABLE:
        raise Exception("AWS not available")
    
    location_map = {
        "us-east-1": "US East (N. Virginia)",
        "us-west-2": "US West (Oregon)",
        "ap-south-1": "Asia Pacific (Mumbai)",
        "eu-west-1": "EU (Ireland)",
    }
    os_map = {"ubuntu": "Linux", "amazon-linux": "Linux", "linux": "Linux", "windows": "Windows"}
    location = location_map.get(region)
    operating_system = os_map.get(os)
    
    if not location:
        raise Exception(f"Region {region} not supported")
    if not operating_system:
        raise Exception(f"Operating system {os} not supported")
    
    filters = [
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
    ]
    response = pricing_client.get_products(ServiceCode="AmazonEC2", Filters=filters, MaxResults=1)
    if not response["PriceList"]:
        raise Exception(f"No pricing data found for {instance_type} in {region}")
    
    price_item = json.loads(response["PriceList"][0])
    on_demand_terms = price_item["terms"]["OnDemand"]
    price_dimensions = list(on_demand_terms.values())[0]["priceDimensions"]
    price_str = list(price_dimensions.values())[0]["pricePerUnit"]["USD"]
    return float(price_str)