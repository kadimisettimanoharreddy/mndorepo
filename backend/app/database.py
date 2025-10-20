# backend/app/database.py
import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine, event, pool, text
from .config import DATABASE_URL

logger = logging.getLogger(__name__)

def create_sync_db_url(async_url: str) -> str:
    """Convert async PostgreSQL URL to sync version"""
    if "postgresql+asyncpg://" in async_url:
        return async_url.replace("postgresql+asyncpg://", "postgresql://")
    elif "postgresql://" in async_url and "+asyncpg" not in async_url:
        return async_url
    elif "+asyncpg" in async_url:
        return async_url.replace("+asyncpg", "")
    else:
        return async_url



engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=15,               
    pool_recycle=1800,          
    max_overflow=25,            
    pool_pre_ping=True,         
    pool_timeout=60,            
    connect_args={
        "command_timeout": 60,   
        "server_settings": {
            "application_name": "aiops_async",
        }
    }
)


AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)



sync_db_url = create_sync_db_url(DATABASE_URL)
sync_engine = create_engine(
    sync_db_url,
    pool_pre_ping=True,         
    echo=False,
    pool_size=15,               
    max_overflow=25,            
    pool_timeout=60,            
    pool_recycle=1800,          
    poolclass=pool.QueuePool,   
    connect_args={
        "application_name": "aiops_sync",
        "options": "-c timezone=UTC"
    }
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine, 
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)


@event.listens_for(sync_engine, "connect")
def set_postgresql_params(dbapi_connection, connection_record):
    """Set connection parameters for PostgreSQL"""
    if hasattr(dbapi_connection, 'execute'):
        try:
            
            dbapi_connection.execute("SET statement_timeout = '60s'")
        except Exception as e:
            logger.warning(f"Could not set statement timeout: {e}")


Base = declarative_base()


async def get_db():
    """Async database dependency for FastAPI"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


def get_infra_sync(request_identifier: str):
    """
    Synchronous database function for Celery workers
    Production-ready with enhanced error handling
    """
    from .models import InfrastructureRequest
    session = None
    try:
        session = SyncSessionLocal()
        
        
        session.execute(text("SELECT 1"))
        
      
        query = session.query(InfrastructureRequest).filter(
            InfrastructureRequest.request_identifier == request_identifier
        )
        result = query.one_or_none()
        
        if result:
            logger.info(f"Found infrastructure request: {request_identifier}")
        else:
            logger.warning(f"Infrastructure request not found: {request_identifier}")
            
        return result
        
    except Exception as e:
        logger.exception(f"Error in get_infra_sync for {request_identifier}: {e}")
        if session:
            try:
                session.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")
        return None
        
    finally:
        if session:
            try:
                session.close()
            except Exception as close_error:
                logger.error(f"Error closing session: {close_error}")


def test_db_connection_sync() -> bool:
    """Test synchronous database connection"""
    try:
        with SyncSessionLocal() as session:
            session.execute(text("SELECT 1"))
            logger.info("Sync database connection test successful")
            return True
    except Exception as e:
        logger.error(f"Sync database connection test failed: {e}")
        return False


async def test_db_connection_async() -> bool:
    """Test asynchronous database connection"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            logger.info("Async database connection test successful")
            return True
    except Exception as e:
        logger.error(f"Async database connection test failed: {e}")
        return False


def get_db_stats():
    """Get database connection pool statistics"""
    try:
        sync_pool = sync_engine.pool
        async_pool = engine.pool
        
        def get_pool_stats(pool):
            stats = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow()
            }
            # Only add invalid if method exists
            if hasattr(pool, 'invalid'):
                try:
                    stats["invalid"] = pool.invalid()
                except Exception:
                    stats["invalid"] = "unavailable"
            else:
                stats["invalid"] = "not_supported"
            return stats
        
        return {
            "sync_pool": get_pool_stats(sync_pool),
            "async_pool": get_pool_stats(async_pool)
        }
    except Exception as e:
        logger.error(f"Error getting DB stats: {e}")
        return {"error": str(e), "pools_available": False}


def create_db_session_sync():
    """Create a new synchronous database session"""
    return SyncSessionLocal()


def execute_query_sync(query_text: str, params: dict = None):
    """Execute a raw SQL query synchronously with proper text() wrapping"""
    session = None
    try:
        session = SyncSessionLocal()
        if params:
            result = session.execute(text(query_text), params)
        else:
            result = session.execute(text(query_text))
        session.commit()
        return result
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()



def get_connection_health():
    """Get detailed connection health information"""
    try:
        sync_healthy = test_db_connection_sync()
        stats = get_db_stats()
        
        return {
            "sync_connection_healthy": sync_healthy,
            "connection_stats": stats,
            "pool_pre_ping_enabled": True,
            "checkout_listener_removed": True,
            "status": "healthy" if sync_healthy else "degraded"
        }
    except Exception as e:
        logger.error(f"Error checking connection health: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }