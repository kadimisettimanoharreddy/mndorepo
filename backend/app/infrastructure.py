from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text, update
from typing import Dict, Any, Optional
import logging
from datetime import datetime
from uuid import UUID, uuid4

from .database import get_db, AsyncSessionLocal
from .models import User, InfrastructureRequest, TerraformState, UserNotification
from .schemas import InfrastructureRequestCreate
from .utils import get_current_user, sanitize_deployment_details, normalize_resource_ids
from .config import API_TOKEN

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])

def verify_github_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    try:
        token_type, token = authorization.split(" ", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    if token_type.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid token type")
    if not API_TOKEN or token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return True

@router.post("/request")
async def create_infrastructure_request_endpoint(
    request_data: InfrastructureRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        await db.execute(text("SELECT 1"))
        db_request = InfrastructureRequest(
            user_id=current_user.id,
            request_identifier=request_data.request_identifier,
            cloud_provider=request_data.cloud_provider,
            environment=request_data.environment,
            resource_type=request_data.resource_type,
            request_parameters=request_data.parameters,
            status="pending",
            hidden=False
        )
        db.add(db_request)
        await db.commit()
        await db.refresh(db_request)
        try:
            from .tasks import process_infrastructure_request
            task_result = process_infrastructure_request.delay(request_data.request_identifier, current_user.email)
            logger.info(f"Dispatched Celery task {task_result.id} for request {request_data.request_identifier}")
        except Exception as e:
            logger.exception(f"Failed to dispatch Celery task: {e}")
            try:
                db_request.status = "task_dispatch_failed"
                await db.commit()
            except Exception:
                pass
        logger.info(f"Infrastructure request created: {request_data.request_identifier}")
        return {
            "message": "Infrastructure request created successfully",
            "request_id": request_data.request_identifier,
            "status": "pending"
        }
    except Exception as e:
        logger.exception(f"Error creating infrastructure request: {str(e)}")
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to create infrastructure request")

@router.get("/requests")
async def get_user_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        await db.execute(text("SELECT 1"))
        result = await db.execute(
            select(InfrastructureRequest, TerraformState)
            .outerjoin(TerraformState, InfrastructureRequest.request_identifier == TerraformState.request_identifier)
            .where(
                InfrastructureRequest.user_id == current_user.id,
                InfrastructureRequest.hidden != True
            )
            .order_by(InfrastructureRequest.created_at.desc())
        )
        requests = []
        status_map = {
            "pending": "Pending Approval",
            "pending_approval": "PR Pending",
            "deployed": "Success",
            "failed": "Failed",
            "task_dispatch_failed": "Failed"
        }
        for request, state in result.all():
            display_status = status_map.get(request.status, request.status)
            request_data = {
                "id": str(request.id),
                "request_identifier": request.request_identifier,
                "cloud_provider": request.cloud_provider,
                "environment": request.environment,
                "resource_type": request.resource_type,
                "status": display_status,
                "created_at": request.created_at.isoformat(),
                "pr_number": request.pr_number,
                "deployed_at": request.deployed_at.isoformat() if request.deployed_at else None
            }
            if state:
                if state.terraform_outputs:
                    from .utils import extract_clean_value
                    
                    # Determine service type for proper output handling
                    service_type = request.resource_type or "ec2"
                    if request.request_identifier.startswith("s3_"):
                        service_type = "s3"
                    elif request.request_identifier.startswith("lambda_"):
                        service_type = "lambda"
                    elif request.request_identifier.startswith("ec2_"):
                        service_type = "ec2"
                    
                    if service_type == "ec2":
                        deployment_details = {
                            "service_type": "ec2",
                            "instance_id": extract_clean_value(state.terraform_outputs.get("instance_id", "")),
                            "ip_address": extract_clean_value(state.terraform_outputs.get("public_ip", state.terraform_outputs.get("private_ip", ""))),
                            "ip_type": extract_clean_value(state.terraform_outputs.get("ip_type", "Public" if state.terraform_outputs.get("public_ip") else "Private")),
                            "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                            "resource_name": extract_clean_value(state.terraform_outputs.get("instance_name", request.request_identifier.split('_')[-1])),
                            "region": extract_clean_value(state.terraform_outputs.get("availability_zone", "us-east-1"))
                        }
                    elif service_type == "s3":
                        deployment_details = {
                            "service_type": "s3",
                            "bucket_name": extract_clean_value(state.terraform_outputs.get("bucket_name", "")),
                            "bucket_arn": extract_clean_value(state.terraform_outputs.get("bucket_arn", "")),
                            "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                            "resource_name": extract_clean_value(state.terraform_outputs.get("bucket_name", request.request_identifier.split('_')[-1])),
                            "region": extract_clean_value(state.terraform_outputs.get("bucket_region", state.terraform_outputs.get("region", "us-east-1"))),
                            "bucket_domain": extract_clean_value(state.terraform_outputs.get("bucket_domain_name", ""))
                        }
                    elif service_type == "lambda":
                        deployment_details = {
                            "service_type": "lambda",
                            "function_name": extract_clean_value(state.terraform_outputs.get("function_name", "")),
                            "function_arn": extract_clean_value(state.terraform_outputs.get("function_arn", "")),
                            "function_url": extract_clean_value(state.terraform_outputs.get("function_url", "")),
                            "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                            "resource_name": extract_clean_value(state.terraform_outputs.get("function_name", request.request_identifier.split('_')[-1])),
                            "region": extract_clean_value(state.terraform_outputs.get("region", "us-east-1")),
                            "runtime": extract_clean_value(state.terraform_outputs.get("runtime", ""))
                        }
                    else:
                        deployment_details = {
                            "service_type": "unknown",
                            "resource_name": request.request_identifier.split('_')[-1],
                            "region": "us-east-1"
                        }
                    
                    request_data["resources"] = deployment_details
                elif state.resource_ids:
                    clean_resources = sanitize_deployment_details(state.resource_ids)
                    request_data["resources"] = clean_resources
            requests.append(request_data)
        return {"requests": requests}
    except Exception as e:
        logger.exception("Error fetching user requests")
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to fetch requests")

@router.delete("/clear-requests")
@router.delete("/api/user/clear-requests")
async def clear_user_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        await db.execute(text("SELECT 1"))
        result = await db.execute(
            update(InfrastructureRequest)
            .where(
                InfrastructureRequest.user_id == current_user.id,
                InfrastructureRequest.hidden != True
            )
            .values(hidden=True)
        )
        await db.commit()
        logger.info(f"Cleared {result.rowcount} requests for user {current_user.email}")
        return {"message": f"Cleared {result.rowcount} requests from display"}
    except Exception as e:
        logger.error(f"Failed to clear requests for {current_user.email}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to clear requests")

async def create_infrastructure_request(request_data: Dict[str, Any]) -> str:
    session = None
    try:
        logger.info(f"Creating infrastructure request: {request_data}")
        session = AsyncSessionLocal()
        await session.execute(text("SELECT 1"))
        req_id = request_data.get("request_identifier")
        if not req_id:
            raise ValueError("request_identifier is required")
        user_email = request_data.get("user_email") or request_data.get("created_by")
        if not user_email:
            raise ValueError("user_email must be provided")
        user_result = await session.execute(select(User).where(User.email == user_email))
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            resolved_user_id = user_obj.id
            logger.info(f"Found existing user: {user_email}")
        else:
            new_user = User(
                id=uuid4(),
                email=user_email,
                password_hash="temp_hash_for_test_user",  
                name=user_email.split("@")[0],
                department=request_data.get("department", "unknown"),
                manager_email=request_data.get("manager_email", "manager@example.com") 
            )
            session.add(new_user)
            await session.flush()
            resolved_user_id = new_user.id
            logger.info(f"Created new user: {user_email} with ID: {resolved_user_id}")
        
        # Determine service type from request_id or parameters
        service_type = "ec2"  # default
        if req_id.startswith("s3_"):
            service_type = "s3"
        elif req_id.startswith("lambda_"):
            service_type = "lambda"
        elif req_id.startswith("ec2_"):
            service_type = "ec2"
        else:
            # Check parameters for service type
            params = request_data.get("parameters", {})
            if params.get("bucket_name"):
                service_type = "s3"
            elif params.get("function_name"):
                service_type = "lambda"
            else:
                service_type = "ec2"
        
        logger.info(f"🔧 Detected service type: {service_type} for request: {req_id}")
        
        # Generate tfvars using MCP service BEFORE creating DB record
        try:
            import httpx
            from pathlib import Path
            
            # Prepare parameters with service type
            tfvar_params = request_data.get("parameters", {}).copy()
            tfvar_params["service_type"] = service_type
            tfvar_params["resource_type"] = service_type
            
            # Call MCP service with service type
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8001/mcp/generate-tfvars",
                    json={
                        "request_id": req_id,
                        "parameters": tfvar_params,
                        "service_type": service_type
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    tfvars_content = result["tfvars_content"]
                    
                    # Create tfvars file
                    environment = tfvar_params.get("environment", "dev")
                    tfvars_dir = Path(f"terraform/environments/aws/{environment}/requests")
                    tfvars_dir.mkdir(parents=True, exist_ok=True)
                    
                    tfvars_file = tfvars_dir / f"{req_id}.tfvars"
                    with open(tfvars_file, "w") as f:
                        f.write(tfvars_content)
                    
                    logger.info(f"✅ MCP generated {service_type} tfvars: {tfvars_file}")
                else:
                    error_text = response.text if response.content else "Unknown error"
                    raise Exception(f"MCP service failed: {response.status_code} - {error_text}")
                    
        except Exception as e:
            logger.error(f"❌ MCP {service_type} tfvars generation failed: {e}")
            raise ValueError(f"Failed to generate {service_type} tfvars: {e}")
        
        # Store with detected service type
        db_request = InfrastructureRequest(
            user_id=resolved_user_id,
            request_identifier=req_id,
            cloud_provider=request_data.get("cloud_provider", "aws"),
            environment=request_data.get("environment", "dev"),
            resource_type=service_type,  # Use detected service type
            request_parameters=request_data.get("parameters", {}),
            status="pending",
            hidden=False
        )
        session.add(db_request)
        await session.commit()
        await session.refresh(db_request)
        logger.info(f"Created infrastructure request in database: {req_id}")
        try:
            from .tasks import process_infrastructure_request
            task_result = process_infrastructure_request.delay(req_id, user_email)
            logger.info(f"SUCCESS: Dispatched Celery task {task_result.id} for request {req_id}")
        except Exception as e:
            logger.error(f"FAILED to dispatch Celery task for {req_id}: {e}")
            try:
                db_request.status = "task_dispatch_failed"
                await session.commit()
            except Exception:
                pass
        return req_id
    except Exception as e:
        logger.exception(f"Error in create_infrastructure_request: {e}")
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        raise
    finally:
        if session:
            try:
                await session.close()
            except Exception as e:
                logger.error(f"Error closing infrastructure session: {e}")

@router.post("/store-state")
async def store_terraform_state(
    state_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_github_token)
):
    try:
        await db.execute(text("SELECT 1"))
        request_id = state_data.get("request_identifier")
        if not request_id:
            raise HTTPException(status_code=400, detail="request_identifier is required")
        logger.info(f"STORE-STATE CALLED for request: {request_id}")
        logger.info(f"Raw state_data keys: {list(state_data.keys())}")
        logger.info(f"Status: {state_data.get('status')}")
        logger.info(f"Outputs present: {bool(state_data.get('outputs'))}")
        if state_data.get('outputs'):
            logger.info(f"Output keys: {list(state_data.get('outputs', {}).keys())}")
        result = await db.execute(
            select(InfrastructureRequest).where(
                InfrastructureRequest.request_identifier == request_id
            )
        )
        infra_request = result.scalar_one_or_none()
        if not infra_request:
            logger.error(f"Infrastructure request not found: {request_id}")
            raise HTTPException(status_code=404, detail="Infrastructure request not found")

        user_result = await db.execute(select(User).where(User.id == infra_request.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            logger.error(f"User not found for request: {request_id}")
            raise HTTPException(status_code=404, detail="User not found")

        existing_state_result = await db.execute(
            select(TerraformState).where(
                TerraformState.request_identifier == request_id
            )
        )
        terraform_state = existing_state_result.scalar_one_or_none()
        clean_resource_ids = normalize_resource_ids(state_data)
        safe_resource_ids = sanitize_deployment_details(clean_resource_ids)
        
        state_file_content = state_data.get("terraform_state") or state_data.get("terraform_state_file", "")
        
        
        terraform_outputs = state_data.get("outputs", {})
        
        if terraform_state:
            terraform_state.terraform_outputs = terraform_outputs
            terraform_state.resource_ids = safe_resource_ids
            terraform_state.status = state_data.get("status", "deployed")
            logger.info(f"Updated existing Terraform state for: {request_id}")
        else:
            terraform_state = TerraformState(
                request_id=infra_request.id,
                user_id=infra_request.user_id,
                request_identifier=request_id,
                cloud_provider=state_data.get("cloud_provider", infra_request.cloud_provider),
                environment=state_data.get("environment", infra_request.environment),
                terraform_outputs=terraform_outputs,
                resource_ids=safe_resource_ids,
                status=state_data.get("status", "deployed")
            )
            db.add(terraform_state)
            logger.info(f"Created new Terraform state for: {request_id}")
        
        status = state_data.get("status", "deployed")
        
        if status == "deployed":
            infra_request.status = "deployed"
            infra_request.deployed_at = datetime.utcnow()
        elif status == "failed":
            infra_request.status = "failed"
        
        await db.commit()
        logger.info(f" Successfully stored Terraform state for request {request_id}")
        
        
        if status == "deployed" and terraform_outputs:
            from .utils import extract_clean_value
            
            logger.info(f"Processing terraform outputs for notifications: {terraform_outputs}")
            
            # Determine service type from request_id or resource_type
            service_type = infra_request.resource_type or "ec2"
            if not service_type or service_type == "unknown":
                if request_id.startswith("s3_"):
                    service_type = "s3"
                elif request_id.startswith("lambda_"):
                    service_type = "lambda"
                elif request_id.startswith("ec2_"):
                    service_type = "ec2"
                else:
                    # Check parameters for service type
                    params = infra_request.request_parameters or {}
                    if params.get("bucket_name"):
                        service_type = "s3"
                    elif params.get("function_name"):
                        service_type = "lambda"
                    else:
                        service_type = "ec2"
            
            logger.info(f"Detected service type: {service_type} for {request_id}")
            
            # Service-specific output processing
            if service_type == "ec2":
                # EC2 Instance outputs
                instance_id = extract_clean_value(terraform_outputs.get("instance_id", ""))
                public_ip = extract_clean_value(terraform_outputs.get("public_ip", ""))
                private_ip = extract_clean_value(terraform_outputs.get("private_ip", ""))
                ip_type = extract_clean_value(terraform_outputs.get("ip_type", ""))
                console_url = extract_clean_value(terraform_outputs.get("console_url", ""))
                instance_name = extract_clean_value(terraform_outputs.get("instance_name", ""))
                availability_zone = extract_clean_value(terraform_outputs.get("availability_zone", ""))
                
                ip_address = public_ip or private_ip
                if not ip_type:
                    ip_type = "Public" if public_ip else "Private" if private_ip else ""
                
                deployment_details = {
                    "service_type": "ec2",
                    "instance_id": instance_id,
                    "ip_address": ip_address,
                    "ip_type": ip_type,
                    "console_url": console_url,
                    "resource_name": instance_name or request_id.split('_')[-1],
                    "region": availability_zone or infra_request.request_parameters.get("region", "us-east-1"),
                    "deployment_time": datetime.utcnow().isoformat(),
                    "instance_type": infra_request.request_parameters.get("instance_type", "t3.micro"),
                    "operating_system": infra_request.request_parameters.get("operating_system", "ubuntu")
                }
                
                resource_ready = bool(instance_id)
                
            elif service_type == "s3":
                # S3 Bucket outputs
                bucket_name = extract_clean_value(terraform_outputs.get("bucket_name", ""))
                bucket_arn = extract_clean_value(terraform_outputs.get("bucket_arn", ""))
                bucket_region = extract_clean_value(terraform_outputs.get("bucket_region", ""))
                console_url = extract_clean_value(terraform_outputs.get("console_url", ""))
                bucket_domain = extract_clean_value(terraform_outputs.get("bucket_domain_name", ""))
                
                deployment_details = {
                    "service_type": "s3",
                    "bucket_name": bucket_name,
                    "bucket_arn": bucket_arn,
                    "region": bucket_region or infra_request.request_parameters.get("region", "us-east-1"),
                    "console_url": console_url,
                    "bucket_domain": bucket_domain,
                    "resource_name": bucket_name or request_id.split('_')[-1],
                    "deployment_time": datetime.utcnow().isoformat(),
                    "versioning_enabled": infra_request.request_parameters.get("versioning_enabled", False),
                    "public_access": infra_request.request_parameters.get("public_access", False)
                }
                
                resource_ready = bool(bucket_name)
                
            elif service_type == "lambda":
                # Lambda Function outputs
                function_name = extract_clean_value(terraform_outputs.get("function_name", ""))
                function_arn = extract_clean_value(terraform_outputs.get("function_arn", ""))
                function_url = extract_clean_value(terraform_outputs.get("function_url", ""))
                runtime = extract_clean_value(terraform_outputs.get("runtime", ""))
                console_url = extract_clean_value(terraform_outputs.get("console_url", ""))
                
                deployment_details = {
                    "service_type": "lambda",
                    "function_name": function_name,
                    "function_arn": function_arn,
                    "function_url": function_url,
                    "runtime": runtime or infra_request.request_parameters.get("runtime", "python3.9"),
                    "console_url": console_url,
                    "resource_name": function_name or request_id.split('_')[-1],
                    "region": infra_request.request_parameters.get("region", "us-east-1"),
                    "deployment_time": datetime.utcnow().isoformat(),
                    "memory_size": infra_request.request_parameters.get("memory_size", 128),
                    "timeout": infra_request.request_parameters.get("timeout", 30)
                }
                
                resource_ready = bool(function_name)
                
            else:
                # Generic fallback
                deployment_details = {
                    "service_type": "unknown",
                    "resource_name": request_id.split('_')[-1],
                    "region": infra_request.request_parameters.get("region", "us-east-1"),
                    "deployment_time": datetime.utcnow().isoformat()
                }
                resource_ready = False
            
            logger.info(f"Extracted {service_type} deployment details: {deployment_details}")
            
            # Send notifications if resource is ready
            if resource_ready:
                from .notification_handler import send_deployment_notifications
                await send_deployment_notifications(user.email, request_id, deployment_details)
                logger.info(f"✅ Sent {service_type} deployment notifications for {request_id}")
                
                # Update dashboard via WebSocket
                from .websocket_manager import manager
                await manager.send_personal_message(user.email, {
                    "type": "request_update",
                    "request": {
                        "request_identifier": request_id,
                        "status": "Success",
                        "resources": deployment_details
                    }
                })
                
                logger.info(f"📊 Updated dashboard for {service_type} {request_id} with deployment details")
            else:
                logger.warning(f"No primary resource found in {service_type} terraform outputs for {request_id}: {terraform_outputs}")
        
        elif status == "failed":
            
            error_message = state_data.get("error_message", "Deployment failed")
            from .notification_handler import send_failure_notifications
            await send_failure_notifications(user.email, request_id, error_message)
            logger.info(f" Sent failure notifications for {request_id}")
        
        return {"message": "Terraform state stored successfully", "status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error storing Terraform state: {str(e)}")
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to store Terraform state: {str(e)}")


sent_deployment_notifications = set()

@router.post("/notify-deployment")
async def notify_deployment(notification_data: Dict[str, Any], _: bool = Depends(verify_github_token)):
    """Handle deployment notifications from Celery tasks"""
    try:
        request_id = notification_data.get("request_identifier")
        status = notification_data.get("status")
        pr_number = notification_data.get("pr_number")
        user_email = notification_data.get("user_email")
        service_type = notification_data.get("service_type", "ec2")
        
       
        notification_key = f"{request_id}_{status}_{pr_number or 'none'}"
        
        if notification_key in sent_deployment_notifications:
            logger.info(f"Duplicate notification prevented: {notification_key}")
            return {"message": "Notification already sent", "status": "duplicate"}
        
        sent_deployment_notifications.add(notification_key)
        logger.info(f"Processing deployment notification: {request_id} - {status}")
        
        if not request_id:
            raise HTTPException(status_code=400, detail="request_identifier required")
        
        
        if not user_email:
            try:
                from .db_helpers import get_user_email_by_request_sync
                user_email = get_user_email_by_request_sync(request_id)
                if not user_email:
                    raise HTTPException(status_code=404, detail=f"User not found for request: {request_id}")
            except Exception as e:
                logger.exception(f"Failed to get user email for {request_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get user email: {str(e)}")
        
        
        from .notification_handler import (
            send_pr_notifications, send_deployment_notifications, 
            send_failure_notifications, send_destroy_notifications
        )
        
        if status == "pr_created":
            # Use service_type from payload or determine from request_id
            if not service_type or service_type == "ec2":
                if request_id.startswith("s3_"):
                    service_type = "s3"
                elif request_id.startswith("lambda_"):
                    service_type = "lambda"
                elif request_id.startswith("ec2_"):
                    service_type = "ec2"
            
            await send_pr_notifications(user_email, request_id, pr_number, service_type.upper())
            logger.info(f"Sent {service_type.upper()} PR notification to {user_email} for {request_id}")
            
        elif status == "deployed":
            # Use service_type from payload or determine from request_id
            if not service_type or service_type == "ec2":
                if request_id.startswith("s3_"):
                    service_type = "s3"
                elif request_id.startswith("lambda_"):
                    service_type = "lambda"
                elif request_id.startswith("ec2_"):
                    service_type = "ec2"
            
            outputs = notification_data.get("outputs", {})
            logger.info(f"Deployment notification - Raw outputs for {service_type}: {outputs}")
            
            from .utils import extract_clean_value
            
            if service_type == "ec2":
                deployment_details = {
                    "service_type": "ec2",
                    "instance_id": extract_clean_value(outputs.get("instance_id", "")),
                    "ip_address": extract_clean_value(outputs.get("public_ip", outputs.get("private_ip", ""))),
                    "ip_type": extract_clean_value(outputs.get("ip_type", "Public" if outputs.get("public_ip") else "Private")),
                    "console_url": extract_clean_value(outputs.get("console_url", "")),
                    "resource_name": extract_clean_value(outputs.get("instance_name", request_id.split('_')[-1])),
                    "region": extract_clean_value(outputs.get("availability_zone", "us-east-1")),
                    "deployment_time": datetime.utcnow().isoformat()
                }
                resource_ready = bool(deployment_details.get("instance_id"))
                
            elif service_type == "s3":
                deployment_details = {
                    "service_type": "s3",
                    "bucket_name": extract_clean_value(outputs.get("bucket_name", "")),
                    "bucket_arn": extract_clean_value(outputs.get("bucket_arn", "")),
                    "console_url": extract_clean_value(outputs.get("console_url", "")),
                    "resource_name": extract_clean_value(outputs.get("bucket_name", request_id.split('_')[-1])),
                    "region": extract_clean_value(outputs.get("region", "us-east-1")),
                    "deployment_time": datetime.utcnow().isoformat()
                }
                resource_ready = bool(deployment_details.get("bucket_name"))
                
            elif service_type == "lambda":
                deployment_details = {
                    "service_type": "lambda",
                    "function_name": extract_clean_value(outputs.get("function_name", "")),
                    "function_arn": extract_clean_value(outputs.get("function_arn", "")),
                    "function_url": extract_clean_value(outputs.get("function_url", "")),
                    "console_url": extract_clean_value(outputs.get("console_url", "")),
                    "resource_name": extract_clean_value(outputs.get("function_name", request_id.split('_')[-1])),
                    "region": extract_clean_value(outputs.get("region", "us-east-1")),
                    "deployment_time": datetime.utcnow().isoformat()
                }
                resource_ready = bool(deployment_details.get("function_name"))
            else:
                deployment_details = {
                    "service_type": "unknown",
                    "resource_name": request_id.split('_')[-1],
                    "deployment_time": datetime.utcnow().isoformat()
                }
                resource_ready = False
            
            logger.info(f"Deployment notification - Processed {service_type} details: {deployment_details}")
            
            if resource_ready:
                await send_deployment_notifications(user_email, request_id, deployment_details)
            else:
                logger.warning(f"No primary resource found in {service_type} deployment notification for {request_id}")
            
        elif status == "failed":
            error_msg = notification_data.get("error_message", "Deployment failed")
            
            # Use service_type from payload or determine from request_id
            if not service_type or service_type == "ec2":
                if request_id.startswith("s3_"):
                    service_type = "s3"
                elif request_id.startswith("lambda_"):
                    service_type = "lambda"
                elif request_id.startswith("ec2_"):
                    service_type = "ec2"
            
            await send_failure_notifications(user_email, request_id, error_msg, service_type.upper())
            
        elif status == "destroyed":
            await send_destroy_notifications(user_email, request_id)
        
      
        from .database import AsyncSessionLocal
        from .models import InfrastructureRequest
        from sqlalchemy.future import select
        from sqlalchemy import update
        
        try:
            async with AsyncSessionLocal() as db:
                # Update request status in database
                await db.execute(
                    update(InfrastructureRequest)
                    .where(InfrastructureRequest.request_identifier == request_id)
                    .values(status=status)
                )
                await db.commit()
                logger.info(f"Updated request {request_id} status to {status}")
                
                
                from .websocket_manager import manager
                if manager.is_user_connected(user_email):
                    from .models import TerraformState
                    
                    result = await db.execute(
                        select(InfrastructureRequest, TerraformState)
                        .outerjoin(TerraformState, InfrastructureRequest.request_identifier == TerraformState.request_identifier)
                        .where(InfrastructureRequest.request_identifier == request_id)
                    )
                    request_data = result.first()
                    
                    if request_data:
                        request, state = request_data
                        status_map = {
                            "pending": "Pending Approval",
                            "pending_approval": "PR Pending", 
                            "pr_created": "PR Pending",
                            "deployed": "Success",
                            "failed": "Failed"
                        }
                        
                        updated_request = {
                            "id": str(request.id),
                            "request_identifier": request.request_identifier,
                            "cloud_provider": request.cloud_provider,
                            "environment": request.environment,
                            "resource_type": request.resource_type,
                            "status": status_map.get(request.status, request.status),
                            "created_at": request.created_at.isoformat(),
                            "pr_number": request.pr_number,
                            "deployed_at": request.deployed_at.isoformat() if request.deployed_at else None
                        }
                        
                        if state:
                            if state.terraform_outputs:
                                from .utils import extract_clean_value
                                
                                # Determine service type for proper dashboard update
                                service_type = request.resource_type or "ec2"
                                if request_id.startswith("s3_"):
                                    service_type = "s3"
                                elif request_id.startswith("lambda_"):
                                    service_type = "lambda"
                                elif request_id.startswith("ec2_"):
                                    service_type = "ec2"
                                
                                if service_type == "ec2":
                                    deployment_details = {
                                        "service_type": "ec2",
                                        "instance_id": extract_clean_value(state.terraform_outputs.get("instance_id", "")),
                                        "ip_address": extract_clean_value(state.terraform_outputs.get("public_ip", state.terraform_outputs.get("private_ip", ""))),
                                        "ip_type": extract_clean_value(state.terraform_outputs.get("ip_type", "Public" if state.terraform_outputs.get("public_ip") else "Private")),
                                        "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                                        "resource_name": extract_clean_value(state.terraform_outputs.get("instance_name", request_id.split('_')[-1])),
                                        "region": extract_clean_value(state.terraform_outputs.get("availability_zone", "us-east-1"))
                                    }
                                elif service_type == "s3":
                                    deployment_details = {
                                        "service_type": "s3",
                                        "bucket_name": extract_clean_value(state.terraform_outputs.get("bucket_name", "")),
                                        "bucket_arn": extract_clean_value(state.terraform_outputs.get("bucket_arn", "")),
                                        "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                                        "resource_name": extract_clean_value(state.terraform_outputs.get("bucket_name", request_id.split('_')[-1])),
                                        "region": extract_clean_value(state.terraform_outputs.get("bucket_region", state.terraform_outputs.get("region", "us-east-1"))),
                                        "bucket_domain": extract_clean_value(state.terraform_outputs.get("bucket_domain_name", ""))
                                    }
                                elif service_type == "lambda":
                                    deployment_details = {
                                        "service_type": "lambda",
                                        "function_name": extract_clean_value(state.terraform_outputs.get("function_name", "")),
                                        "function_arn": extract_clean_value(state.terraform_outputs.get("function_arn", "")),
                                        "function_url": extract_clean_value(state.terraform_outputs.get("function_url", "")),
                                        "console_url": extract_clean_value(state.terraform_outputs.get("console_url", "")),
                                        "resource_name": extract_clean_value(state.terraform_outputs.get("function_name", request_id.split('_')[-1])),
                                        "region": extract_clean_value(state.terraform_outputs.get("region", "us-east-1")),
                                        "runtime": extract_clean_value(state.terraform_outputs.get("runtime", ""))
                                    }
                                else:
                                    deployment_details = {
                                        "service_type": "unknown",
                                        "resource_name": request_id.split('_')[-1],
                                        "region": "us-east-1"
                                    }
                                
                                updated_request["resources"] = deployment_details
                            elif state.resource_ids:
                                from .utils import sanitize_deployment_details
                                clean_resources = sanitize_deployment_details(state.resource_ids)
                                updated_request["resources"] = clean_resources
                        
                        await manager.send_personal_message(user_email, {
                            "type": "request_update",
                            "request": updated_request
                        })
                        logger.info(f"Sent dashboard update for {request_id}")
        except Exception as e:
            logger.error(f"Failed to update request status: {e}")
        
        return {"message": "Notification sent successfully", "status": "success"}
        
    except Exception as e:
        logger.error(f"Error handling deployment notification: {e}")
        
        if 'notification_key' in locals():
            sent_deployment_notifications.discard(notification_key)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/health")
async def infrastructure_health():
    try:
        from .database import test_db_connection_async, get_db_stats
        db_connected = await test_db_connection_async()
        db_stats = get_db_stats()
        return {
            "status": "healthy" if db_connected else "unhealthy",
            "service": "infrastructure",
            "timestamp": datetime.utcnow().isoformat(),
            "database_connected": db_connected,
            "connection_stats": db_stats
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "infrastructure",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }