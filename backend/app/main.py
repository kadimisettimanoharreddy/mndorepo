import logging
import asyncio
from fastapi import FastAPI, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from .auth import router as auth_router
from .chat import router as chat_router
from .simple_chat import router as simple_chat_router
from .s3_handler import router as s3_router
from .lambda_handler import router as lambda_router
from .infrastructure import router as infrastructure_router
from .environment_approval import router as environment_router
from .config import ALLOWED_ORIGINS
from .database import engine, Base
from .notification_routes import router as notification_router
from .metrics import MetricsMiddleware, metrics_handler, update_system_metrics
from .permissions import initialize_permissions, PERMISSIONS_MATRIX, get_permissions_status
from .database import get_db
from .utils import get_current_user

from .monitoring_routes import router as monitoring_router
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("aiops_platform")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

app = FastAPI(title="AIOps Platform API", version="1.0.0")

@app.on_event("startup")
async def startup_event():
    try:
        logger.info("Starting application startup process...")
        logger.info("Initializing permissions system...")
        await initialize_permissions()
        logger.info("Permissions initialization completed")
        logger.info("Creating database tables...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully!")
        asyncio.create_task(update_system_metrics())
        logger.info("System metrics collection started")
        logger.info("Application startup complete!")
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise

permissions_router = APIRouter(prefix="/api/permissions", tags=["permissions"])

@permissions_router.get("/matrix")
async def get_permissions_matrix():
    return PERMISSIONS_MATRIX

@permissions_router.get("/status")
async def get_permissions_status_endpoint():
    return get_permissions_status()

app.add_middleware(MetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for ngrok compatibility
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.get("/metrics")
async def metrics():
    return await metrics_handler()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "AIOps Platform API"}

# API router for user endpoints
api_router = APIRouter(prefix="/api/user", tags=["user"])

@api_router.delete("/clear-requests")
async def clear_user_requests_api(
    db=Depends(get_db), 
    current_user=Depends(get_current_user)
):
    from .models import InfrastructureRequest
    from sqlalchemy import update, text
    from fastapi import HTTPException
    
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

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(simple_chat_router)
app.include_router(s3_router)
app.include_router(lambda_router)
app.include_router(infrastructure_router)
app.include_router(notification_router)
app.include_router(environment_router)
app.include_router(permissions_router)
app.include_router(api_router)

app.include_router(monitoring_router)

# Add direct routes for GitHub Actions (to fix 404 errors)
from .infrastructure import store_terraform_state, notify_deployment

@app.post("/infrastructure/store-state")
async def store_state_direct(state_data: dict, db=Depends(get_db)):
    from .infrastructure import verify_github_token
    verify_github_token()
    return await store_terraform_state(state_data, db, True)

@app.post("/infrastructure/notify-deployment")
async def notify_deployment_direct(notification_data: dict):
    from .infrastructure import verify_github_token
    verify_github_token()
    return await notify_deployment(notification_data, True)