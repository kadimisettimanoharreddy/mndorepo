import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from .mcp_tfvars_service import MCPTfvarsService

logger = logging.getLogger(__name__)

class MCPTerraformManager:
    def __init__(self):
        self.mcp_service = MCPTfvarsService()
    
    async def generate_tfvars_for_request(
        self,
        request_identifier: str,
        params: Dict[str, Any] = None,
        user: Optional[Any] = None,
        request_obj: Optional[Any] = None,
        repo_root_override: Optional[str] = None,
    ) -> Tuple[Path, Optional[Path]]:
        
        # Get repo root
        repo_root = Path(repo_root_override) if repo_root_override else Path.cwd()
        
        # Get environment
        environment = params.get("environment", "dev")
        cloud = params.get("cloud_provider", "aws")
        
        # Create requests directory
        requests_dir = repo_root / "terraform" / "environments" / cloud / environment / "requests"
        requests_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate tfvars file path
        tfvars_path = requests_dir / f"{request_identifier}.tfvars"
        
        # Use MCP service to generate content
        success = await self.mcp_service.create_tfvars_file(
            request_identifier, 
            params, 
            str(tfvars_path)
        )
        
        if success:
            logger.info(f"MCP generated tfvars: {tfvars_path}")
            clone_expected = Path("terraform") / "environments" / cloud / environment / "requests" / f"{request_identifier}.tfvars"
            return tfvars_path, clone_expected
        else:
            raise Exception("Failed to generate tfvars using MCP service")

# Replace the original function
async def generate_tfvars_for_request_mcp(request_identifier: str, params: Dict[str, Any] = None, **kwargs):
    manager = MCPTerraformManager()
    return await manager.generate_tfvars_for_request(request_identifier, params, **kwargs)