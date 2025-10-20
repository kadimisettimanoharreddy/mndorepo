from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict
import logging

from .database import get_db
from .models import User, InfrastructureRequest, TerraformState
from .utils import get_current_user, extract_clean_value
from .monitoring import EC2MonitoringService
from typing import Dict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitoring", tags=["monitoring"])

@router.get("/resources")
async def get_user_resources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all deployed EC2 instances for the current user (monitoring only supports EC2)"""
    try:
        # Get only EC2 deployed requests with optional terraform state
        result = await db.execute(
            select(InfrastructureRequest, TerraformState)
            .outerjoin(TerraformState, InfrastructureRequest.id == TerraformState.request_id)
            .where(
                InfrastructureRequest.user_id == current_user.id,
                InfrastructureRequest.status == 'deployed',
                InfrastructureRequest.resource_type == 'ec2'
            )
            .order_by(InfrastructureRequest.created_at.desc())
        )
        
        resources = []
        monitoring_service = EC2MonitoringService()
        
        for request, state in result.all():
            resource_info = {
                "id": str(request.id),
                "name": request.request_identifier,
                "resource_type": "ec2",
                "environment": request.environment,
                "created_at": request.created_at.isoformat(),
                "aws_state": "unknown"
            }
            
            # Handle EC2 instances only
            instance_id = None
            instance_type = 't3.micro'
            
            # Try to get instance info from terraform state first
            if state and state.terraform_outputs:
                outputs = state.terraform_outputs
                instance_id = extract_clean_value(outputs.get('instance_id'))
                instance_type = extract_clean_value(outputs.get('instance_type')) or 't3.micro'
            
            # Fallback to resource_ids if terraform_outputs is empty
            if not instance_id and state and state.resource_ids:
                resource_ids = state.resource_ids
                instance_id = extract_clean_value(resource_ids.get('instance_id'))
                if request.request_parameters:
                    instance_type = request.request_parameters.get('instance_type', 't3.micro')
            
            # Final fallback to request parameters
            if not instance_id and request.request_parameters:
                params = request.request_parameters
                instance_id = params.get('instance_id')
                instance_type = params.get('instance_type', 't3.micro')
            
            resource_info.update({
                "instance_id": instance_id or "pending",
                "type": instance_type
            })
            
            if instance_id:
                try:
                    # Check AWS status
                    aws_status = await monitoring_service.get_instance_status(instance_id)
                    aws_state = aws_status.get('state', 'unknown')
                    resource_info["aws_state"] = aws_state
                    
                    # Only include non-terminated instances
                    if aws_state == 'terminated':
                        request.status = 'terminated'
                        continue
                        
                except Exception as e:
                    error_str = str(e).lower()
                    if 'not found' in error_str or 'does not exist' in error_str:
                        request.status = 'terminated'
                        continue
                    else:
                        resource_info["aws_state"] = 'unknown'
            

            
            resources.append(resource_info)
        
        # Commit any status changes
        await db.commit()
        
        return {"success": True, "data": resources}
    except Exception as e:
        logger.error(f"Error getting user resources: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Keep backward compatibility
@router.get("/instances")
async def get_user_instances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all deployed instances for the current user (backward compatibility)"""
    resources_response = await get_user_resources(db, current_user)
    
    # Filter only EC2 instances for backward compatibility
    instances = []
    for resource in resources_response["data"]:
        if resource.get("resource_type") == "ec2":
            instances.append(resource)
    
    return {"success": True, "data": instances}

@router.get("/instance/{instance_id}/status")
async def get_instance_status(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get real AWS instance status"""
    try:
        monitoring_service = EC2MonitoringService()
        status = await monitoring_service.get_instance_status(instance_id)
        
        
        health = await monitoring_service.get_instance_health(instance_id)
        
        return {
            "success": True, 
            "data": {
                "state": status.get('state', 'unknown'),
                "status_checks": health.get('overall_status', 'unknown'),
                "system_status": health.get('system_status', 'unknown'),
                "instance_type": status.get('instance_type'),
                "public_ip": status.get('public_ip'),
                "private_ip": status.get('private_ip'),
                "launch_time": status.get('launch_time')
            }
        }
    except Exception as e:
        logger.error(f"Error getting instance status: {str(e)}")
        return {"success": False, "data": {"state": "unknown", "status_checks": "unknown", "system_status": "unknown"}}

@router.get("/instance/{instance_id}/metrics")
async def get_instance_metrics(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get CloudWatch metrics for instance"""
    try:
        monitoring_service = EC2MonitoringService()
        metrics = await monitoring_service.get_instance_metrics(instance_id)
        
        
        return {
            "success": True, 
            "data": {
                "cpu": metrics.get('cpu', 0),
                "network_in": metrics.get('network_in', 0),
                "network_out": metrics.get('network_out', 0),
                "memory": metrics.get('memory', 0),
                "timestamp": metrics.get('timestamp')
            }
        }
    except Exception as e:
        logger.error(f"Error getting instance metrics: {str(e)}")
        return {"success": True, "data": {"cpu": 0, "network_in": 0, "network_out": 0, "memory": 0, "timestamp": "2024-01-01T00:00:00Z"}}

@router.post("/instance/{instance_id}/start")
async def start_instance(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Start EC2 instance"""
    try:
        monitoring_service = EC2MonitoringService()
        result = await monitoring_service.start_instance(instance_id)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error starting instance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/instance/{instance_id}/stop")
async def stop_instance(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Stop EC2 instance"""
    try:
        monitoring_service = EC2MonitoringService()
        result = await monitoring_service.stop_instance(instance_id)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error stopping instance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/instance/{instance_id}/restart")
async def restart_instance(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Restart EC2 instance"""
    try:
        monitoring_service = EC2MonitoringService()
        result = await monitoring_service.restart_instance(instance_id)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error restarting instance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/instance/{instance_id}/terminate")
async def terminate_instance_direct(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Terminate EC2 instance and update database (monitoring only supports EC2)"""
    try:
        monitoring_service = EC2MonitoringService()
        result = await monitoring_service.terminate_instance(instance_id)
        
        # Update database to mark as terminated
        update_result = await db.execute(
            select(InfrastructureRequest, TerraformState)
            .outerjoin(TerraformState, InfrastructureRequest.id == TerraformState.request_id)
            .where(
                InfrastructureRequest.user_id == current_user.id,
                InfrastructureRequest.status == 'deployed',
                InfrastructureRequest.resource_type == 'ec2'
            )
        )
        
        for request, state in update_result.all():
            stored_instance_id = None
            
            if state and state.terraform_outputs:
                stored_instance_id = extract_clean_value(state.terraform_outputs.get('instance_id'))
            elif state and state.resource_ids:
                stored_instance_id = extract_clean_value(state.resource_ids.get('instance_id'))
            elif request.request_parameters:
                stored_instance_id = request.request_parameters.get('instance_id')
            
            if stored_instance_id == instance_id:
                request.status = 'terminated'
                break
        
        await db.commit()
        
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error terminating EC2 instance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Keep backward compatibility
@router.post("/instance/{instance_id}/terminate")
async def terminate_instance(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Terminate EC2 instance and update database (backward compatibility)"""
    return await terminate_instance_direct(instance_id, db, current_user)



# Keep backward compatibility
@router.get("/instance/{instance_id}/cost")
async def get_instance_cost(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get real-time cost information from AWS (backward compatibility)"""
    return await get_resource_cost("ec2", instance_id, current_user)



@router.get("/instance/{instance_id}/cost-optimization")
async def get_cost_optimization(
    instance_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get cost optimization suggestions"""
    try:
        monitoring_service = EC2MonitoringService()
        suggestions = await monitoring_service.get_cost_optimization_suggestions(instance_id)
        return {"success": True, "data": suggestions}
    except Exception as e:
        logger.error(f"Error getting cost optimization: {str(e)}")
        return {"success": False, "error": str(e)}

@router.post("/cleanup-terminated")
async def cleanup_terminated_resources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Clean up terminated EC2 instances from monitoring"""
    try:
        # Get all deployed requests
        result = await db.execute(
            select(InfrastructureRequest, TerraformState)
            .outerjoin(TerraformState, InfrastructureRequest.id == TerraformState.request_id)
            .where(
                InfrastructureRequest.user_id == current_user.id,
                InfrastructureRequest.status == 'deployed'
            )
        )
        
        monitoring_service = EC2MonitoringService()
        terminated_count = 0
        
        for request, state in result.all():
            # Only handle EC2 instances
            if request.resource_type != "ec2":
                continue
                
            instance_id = None
            
            if state and state.terraform_outputs:
                instance_id = extract_clean_value(state.terraform_outputs.get('instance_id'))
            elif state and state.resource_ids:
                instance_id = extract_clean_value(state.resource_ids.get('instance_id'))
            elif request.request_parameters:
                instance_id = request.request_parameters.get('instance_id')
            
            if instance_id:
                try:
                    aws_status = await monitoring_service.get_instance_status(instance_id)
                    if aws_status.get('state') == 'terminated':
                        request.status = 'terminated'
                        terminated_count += 1
                except Exception as e:
                    error_str = str(e).lower()
                    if 'not found' in error_str or 'does not exist' in error_str:
                        request.status = 'terminated'
                        terminated_count += 1
        
        await db.commit()
        
        return {
            "success": True, 
            "message": f"Cleaned up {terminated_count} terminated EC2 instances",
            "terminated_count": terminated_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up terminated resources: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))