from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)


AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

API_TOKEN = os.getenv("API_TOKEN", "github-actions-service-token-change-in-production")


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aiopsusers:aiopasswd@localhost:5432/aiopsdatas")


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "your-org")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "conversacloud")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

API_URL = os.getenv("API_URL", "http://localhost:8000")


CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

LLM_INTENT_ENABLED = os.getenv("LLM_INTENT_ENABLED", "true").lower() == "true"


ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://0822e2c1d36a.ngrok-free.app",
    FRONTEND_URL
]
