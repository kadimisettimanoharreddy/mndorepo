from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
import logging
from .database import get_db
from .utils import get_current_user
from .models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lambda", tags=["lambda"])

@router.post("/create-function")
async def create_lambda_function(
    request: Dict[str, Any],
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Handle Lambda function creation requests"""
    try:
        function_name = request.get("function_name")
        runtime = request.get("runtime", "python3.9")
        region = request.get("region", "us-east-1")
        environment = request.get("environment", "dev")
        
        if not function_name:
            raise HTTPException(status_code=400, detail="Function name required")
        
        # Create infrastructure request for Lambda
        from .infrastructure import create_infrastructure_request
        
        request_data = {
            "request_identifier": f"lambda_{current_user.department}_{function_name}_{int(__import__('time').time())}",
            "cloud_provider": "aws",
            "environment": environment,
            "resource_type": "lambda",
            "parameters": {
                "lambda_function_name": function_name,
                "lambda_runtime": runtime,
                "lambda_handler": request.get("handler", "lambda_function.lambda_handler"),
                "lambda_memory_size": request.get("memory_size", 128),
                "lambda_timeout": request.get("timeout", 30),
                "region": region,
                "department": current_user.department,
                "created_by": current_user.email
            },
            "user_email": current_user.email,
            "department": current_user.department
        }
        
        created_request_id = await create_infrastructure_request(request_data)
        
        return {
            "message": f"Lambda function '{function_name}' creation initiated",
            "request_id": created_request_id,
            "status": "pending"
        }
        
    except Exception as e:
        logger.error(f"Lambda creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))