from sqlalchemy.orm import Session
from sqlalchemy.future import select
from .database import SyncSessionLocal  
from .models import User, InfrastructureRequest
import logging

logger = logging.getLogger(__name__)

def get_user_email_by_request_sync(request_identifier: str) -> str:
    """
    FIXED: Use synchronous database connection to avoid event loop conflicts
    This is called from Redis listener (sync context)
    """
    session = None
    try:
        session = SyncSessionLocal()
        
        
        result = session.query(InfrastructureRequest, User).join(
            User, User.id == InfrastructureRequest.user_id
        ).filter(
            InfrastructureRequest.request_identifier == request_identifier
        ).first()
        
        if result:
            infra_request, user = result
            logger.info(f"Found user email for {request_identifier}: {user.email}")
            return user.email
        else:
            logger.warning(f"No user found for request: {request_identifier}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting user email for {request_identifier}: {e}")
        return None
    finally:
        if session:
            session.close()


async def get_user_email_by_request_async(request_identifier: str) -> str:
    """
    Async version for use in FastAPI endpoints
    """
    from .database import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(InfrastructureRequest, User).join(
                    User, User.id == InfrastructureRequest.user_id
                ).where(
                    InfrastructureRequest.request_identifier == request_identifier
                )
            )
            
            row = result.first()
            if row:
                infra_request, user = row
                return user.email
            return None
            
        except Exception as e:
            logger.error(f"Error in async get_user_email: {e}")
            return None
