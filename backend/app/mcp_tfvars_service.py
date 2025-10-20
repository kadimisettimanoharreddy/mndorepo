import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MCPTfvarsService:
    def __init__(self, mcp_url: str = "http://localhost:8001"):
        self.mcp_url = mcp_url
    
    async def generate_tfvars_content(self, request_id: str, params: Dict[str, Any]) -> str:
        """Generate tfvars content using MCP service"""
        try:
            payload = {
                "request_id": request_id,
                "parameters": params,
                "template_type": "terraform_tfvars"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.mcp_url}/mcp/generate-tfvars",
                    json=payload,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("tfvars_content", "")
                else:
                    logger.error(f"MCP tfvars generation failed: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error calling MCP tfvars service: {e}")
            return None
    
    async def create_tfvars_file(self, request_id: str, params: Dict[str, Any], file_path: str) -> bool:
        """Create tfvars file using MCP service"""
        content = await self.generate_tfvars_content(request_id, params)
        
        if content:
            try:
                with open(file_path, 'w') as f:
                    f.write(content)
                logger.info(f"Created tfvars file: {file_path}")
                return True
            except Exception as e:
                logger.error(f"Error writing tfvars file: {e}")
                return False
        
        return False