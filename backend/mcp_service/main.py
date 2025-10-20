# backend/mcp_service/main.py
import uvicorn
from mcp_service.app import app

if __name__ == "__main__":
    uvicorn.run("mcp_service.app:app", host="0.0.0.0", port=8001, reload=True, log_level="info")
