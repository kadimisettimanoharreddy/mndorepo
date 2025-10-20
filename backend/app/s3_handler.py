from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
import logging
from .database import get_db
from .utils import get_current_user
from .models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/s3", tags=["s3"])

@router.post("/create-bucket")
async def create_s3_bucket(
    request: Dict[str, Any],
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Handle S3 bucket creation requests"""
    try:
        bucket_name = request.get("bucket_name")
        region = request.get("region", "us-east-1")
        environment = request.get("environment", "dev")
        
        if not bucket_name:
            raise HTTPException(status_code=400, detail="Bucket name required")
        
        # Create infrastructure request for S3
        from .infrastructure import create_infrastructure_request
        
        request_data = {
            "request_identifier": f"s3_{current_user.department}_{bucket_name}_{int(__import__('time').time())}",
            "cloud_provider": "aws",
            "environment": environment,
            "resource_type": "s3",
            "parameters": {
                "bucket_name": bucket_name,
                "region": region,
                "versioning_enabled": request.get("versioning", True),
                "block_public_access": request.get("block_public", True),
                "department": current_user.department,
                "created_by": current_user.email
            },
            "user_email": current_user.email,
            "department": current_user.department
        }
        
        created_request_id = await create_infrastructure_request(request_data)
        
        return {
            "message": f"S3 bucket '{bucket_name}' creation initiated",
            "request_id": created_request_id,
            "status": "pending"
        }
        
    except Exception as e:
        logger.error(f"S3 creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))