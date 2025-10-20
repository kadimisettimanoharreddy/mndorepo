# backend/app/tasks.py
import logging
import asyncio
import json
import importlib
from celery import Celery
from typing import Dict, Any, Optional
import httpx
import redis

from .config import CELERY_BROKER_URL, API_URL, API_TOKEN, REDIS_URL
from .database import SyncSessionLocal, get_infra_sync
from .models import InfrastructureRequest, User
from sqlalchemy import update, select as sync_select

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

celery_app = Celery("aiops_tasks", broker=CELERY_BROKER_URL)
_redis_client = redis.from_url(REDIS_URL) if REDIS_URL else None


def get_user_sync(user_id):
    """Get user synchronously for Celery workers"""
    try:
        with SyncSessionLocal() as db:
            return db.query(User).filter(User.id == user_id).first()
    except Exception as e:
        logger.error(f"Error fetching user sync: {e}")
        return None


def detect_service_type(parameters: Dict[str, Any]) -> str:
    """Detect service type from parameters"""
    if parameters.get("bucket_name"):
        return "s3"
    elif parameters.get("function_name") or parameters.get("lambda_function_name"):
        return "lambda"
    elif parameters.get("instance_type"):
        return "ec2"
    else:
        return "ec2"  # default


def _update_db_sync(request_identifier: str, pr_number: Optional[int]) -> Dict[str, Any]:
    """Update database synchronously"""
    try:
        with SyncSessionLocal() as db:
            if pr_number:
                result = db.execute(
                    update(InfrastructureRequest)
                    .where(InfrastructureRequest.request_identifier == request_identifier)
                    .values(
                        pr_number=int(pr_number),
                        status="pending_approval"
                    )
                )
            else:
                result = db.execute(
                    update(InfrastructureRequest)
                    .where(InfrastructureRequest.request_identifier == request_identifier)
                    .values(status="pr_failed")
                )
            
            db.commit()
            
            if result.rowcount > 0:
                logger.info("Successfully updated DB for %s with PR #%s", request_identifier, pr_number)
                return {"db_updated": True, "rows_affected": result.rowcount}
            else:
                logger.warning("No rows updated for request %s", request_identifier)
                return {"db_updated": False, "error": "no_rows_affected"}
                
    except Exception as e:
        logger.exception("Failed to update DB for %s: %s", request_identifier, e)
        return {"db_updated": False, "db_error": str(e)}


async def _process_terraform_async(request_identifier: str, infra_payload: Dict[str, Any], user_obj) -> Dict[str, str]:
    """Process terraform generation asynchronously"""
    try:
        tm_mod = importlib.import_module("app.terraform_manager")
        TerraformManager = getattr(tm_mod, "TerraformManager")
        tm = TerraformManager()
        
        backend_path, clone_expected_path = await tm.generate_tfvars_for_request(
            request_identifier, 
            params=infra_payload.get("request_parameters", {}),
            user=user_obj,
            request_obj=infra_payload
        )
        
        logger.info("Local TFVARS generated for %s -> %s", request_identifier, backend_path)
        return {
            "tfvars_backend_path": str(backend_path),
            "tfvars_repo_path": str(clone_expected_path) if clone_expected_path else None,
            "status": "success"
        }
    except Exception as e:
        logger.exception("Terraform tfvars generation failed for %s: %s", request_identifier, e)
        return {"status": "failed", "error": str(e)}


async def _process_github_async(request_identifier: str) -> Dict[str, Any]:
    """Process GitHub PR creation asynchronously"""
    try:
        gh_mod = importlib.import_module("app.github_manager")
        GitHubManager = getattr(gh_mod, "GitHubManager")
        gh = GitHubManager()
        pr_number = await gh.create_pull_request(request_identifier)
        
        if pr_number:
            logger.info("Created PR #%s for request %s", pr_number, request_identifier)
            return {"pr_number": pr_number, "status": "pr_created"}
        else:
            return {"pr_number": None, "status": "pr_failed"}
    except Exception as e:
        logger.exception("GitHubManager failed to create PR for %s: %s", request_identifier, e)
        return {"pr_number": None, "status": "pr_failed", "error": str(e)}


async def _send_notification_async(request_identifier: str, user_email: str, status: str, pr_number: Optional[int], service_type: str = "ec2") -> Dict[str, Any]:
    """Send notification asynchronously"""
    try:
        if not API_URL or not API_TOKEN:
            return {"notify_error": "API_URL or API_TOKEN not configured"}

        notify_url = f"{API_URL.rstrip('/')}/infrastructure/notify-deployment"
        payload = {
            "request_identifier": request_identifier,
            "user_email": user_email,
            "status": status,
            "pr_number": pr_number,
            "service_type": service_type,
        }
        headers = {
            "Authorization": f"Bearer {API_TOKEN}", 
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "true"
        }
        
        logger.info(f"Sending notification to: {notify_url}")
        logger.info(f"Notification payload: {payload}")
        logger.info(f"Headers: {headers}")
        
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(notify_url, json=payload, headers=headers)
            logger.info(f"Notification response status: {resp.status_code}")
            logger.info(f"Notification response text: {resp.text}")
            
            if resp.status_code in (200, 201):
                try:
                    return {"notify_response": resp.json() if resp.content else {"status": "ok"}}
                except Exception:
                    return {"notify_response": {"status": "ok"}}
            else:
                return {"notify_status_code": resp.status_code, "notify_error": f"HTTP {resp.status_code}", "response_text": resp.text}
    except Exception as e:
        logger.exception("Failed to notify user API for %s: %s", request_identifier, e)
        return {"notify_error": str(e)}


def _publish_redis_sync(request_identifier: str, pr_number: Optional[int], status: str) -> Dict[str, Any]:
    """Publish to Redis synchronously"""
    try:
        if not _redis_client:
            return {"redis_published": False, "redis_error": "Redis client not configured"}

        channel = f"deployment:{request_identifier}"
        msg = json.dumps({
            "request_id": request_identifier, 
            "pr_number": pr_number, 
            "status": status
        })
        _redis_client.publish(channel, msg)
        return {"redis_published": True}
    except Exception as e:
        logger.exception("Failed to publish Redis message for %s: %s", request_identifier, e)
        return {"redis_published": False, "redis_publish_error": str(e)}


async def _process_request_async_main(request_identifier: str, user_email: str, infra_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Main async processing function with proper error handling"""
    result_payload = {"request_identifier": request_identifier, "status": "failed"}
    
    # Get user object synchronously (converted from async DB call)
    user_obj = None
    if infra_payload.get("user_id"):
        user_obj = get_user_sync(infra_payload["user_id"])
    
    # Determine service type from request identifier and parameters
    service_type = "ec2"  # default
    if request_identifier.startswith("s3_"):
        service_type = "s3"
    elif request_identifier.startswith("lambda_"):
        service_type = "lambda"
    elif request_identifier.startswith("ec2_"):
        service_type = "ec2"
    else:
        # Check parameters for service type
        params = infra_payload.get("request_parameters", {})
        if params.get("bucket_name"):
            service_type = "s3"
        elif params.get("function_name") or params.get("lambda_function_name"):
            service_type = "lambda"
        else:
            service_type = "ec2"
    
    logger.info(f"🔧 Processing {service_type.upper()} service for {request_identifier}")
    
    # Process Terraform for all service types
    terraform_result = await _process_terraform_async(request_identifier, infra_payload, user_obj)
    if terraform_result["status"] == "success":
        result_payload["tfvars_written"] = True
        result_payload["tfvars_backend_path"] = terraform_result["tfvars_backend_path"]
        result_payload["tfvars_repo_path"] = terraform_result["tfvars_repo_path"]
        result_payload["service_type"] = service_type
    else:
        result_payload["tfvars_written"] = False
        result_payload["error"] = f"tfvars_generation_failed: {terraform_result.get('error', 'unknown')}"
        result_payload["service_type"] = service_type
        # Continue processing even if tfvars fail
    
    # Process GitHub PR
    github_result = await _process_github_async(request_identifier)
    result_payload["pr_number"] = github_result.get("pr_number")
    result_payload["status"] = github_result["status"]
    if github_result.get("error"):
        result_payload["error"] = f"pr_creation_failed: {github_result['error']}"
    
    # Send notification with service type
    notification_result = await _send_notification_async(
        request_identifier, 
        user_email, 
        result_payload["status"], 
        result_payload.get("pr_number"),
        service_type
    )
    result_payload.update(notification_result)
    
    return result_payload


@celery_app.task(name="aiops.health_check")
def health_check() -> str:
    return "ok"


@celery_app.task(name="aiops.process_infrastructure_request")
def process_infrastructure_request(request_identifier: str, user_email: str) -> Dict[str, Any]:
    """
    Main Celery task - Uses dedicated event loop for async operations
    """
    try:
        logger.info("Celery task starting processing: %s", request_identifier)

        # Get infrastructure request synchronously
        try:
            infra_row = get_infra_sync(request_identifier)
        except Exception as e:
            logger.exception("Synchronous DB lookup failed for %s: %s", request_identifier, e)
            return {"request_identifier": request_identifier, "status": "failed", "error": f"sync-db-lookup-failed: {e}"}

        if not infra_row:
            logger.error("Request %s not found (sync lookup)", request_identifier)
            return {"request_identifier": request_identifier, "status": "failed", "error": "request-not-found"}

        # Convert to payload dict
        infra_payload = {
            "id": getattr(infra_row, "id", None),
            "request_identifier": getattr(infra_row, "request_identifier", request_identifier),
            "user_id": getattr(infra_row, "user_id", None),
            "user_email": getattr(infra_row, "user_email", user_email),
            "request_parameters": getattr(infra_row, "request_parameters", None),
            "status": getattr(infra_row, "status", None),
            "created_at": getattr(infra_row, "created_at", None),
        }

        # Create dedicated event loop for async operations
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run async processing
            result = loop.run_until_complete(
                _process_request_async_main(request_identifier, user_email, infra_payload)
            )
            
        finally:
            # Clean up event loop properly
            if loop:
                try:
                    # Cancel any remaining tasks
                    pending_tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
                    for task in pending_tasks:
                        task.cancel()
                    
                    # Wait for cancelled tasks to complete
                    if pending_tasks:
                        loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
                except Exception as cleanup_error:
                    logger.warning(f"Error during event loop cleanup: {cleanup_error}")
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass
                    asyncio.set_event_loop(None)
        
        # Update database synchronously
        pr_number = result.get("pr_number")
        db_result = _update_db_sync(request_identifier, pr_number)
        result.update(db_result)
        
        # Publish to Redis synchronously
        redis_result = _publish_redis_sync(request_identifier, pr_number, result.get("status", "failed"))
        result.update(redis_result)
        
        logger.info("Finished processing: %s -> %s", request_identifier, result.get("status"))
        return result

    except Exception as e:
        logger.exception("Error processing request %s: %s", request_identifier, e)
        return {"request_identifier": request_identifier, "status": "failed", "error": str(e)}