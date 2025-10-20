import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MCPCostService:
    """MCP service integration for S3, Lambda, and EC2 costs"""
    
    def __init__(self):
        self.mcp_base_url = "http://localhost:8001/mcp"
    
    async def get_s3_cost(self, region: str, storage_gb: int = 1) -> Dict[str, Any]:
        """Get S3 costs via MCP service"""
        try:
            response = requests.post(
                f"{self.mcp_base_url}/get-s3-cost",
                json={
                    "region": region,
                    "storage_gb": storage_gb
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"MCP S3 cost service failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"MCP S3 cost service error: {e}")
            raise Exception(f"S3 cost estimation unavailable: {str(e)}")
    
    async def get_lambda_cost(self, region: str, memory_mb: int = 128, monthly_requests: int = 1000) -> Dict[str, Any]:
        """Get Lambda costs via MCP service"""
        try:
            response = requests.post(
                f"{self.mcp_base_url}/get-lambda-cost",
                json={
                    "region": region,
                    "memory_mb": memory_mb,
                    "monthly_requests": monthly_requests
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"MCP Lambda cost service failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"MCP Lambda cost service error: {e}")
            raise Exception(f"Lambda cost estimation unavailable: {str(e)}")
    
    async def get_ec2_cost(self, instance_type: str, region: str, operating_system: str) -> Dict[str, Any]:
        """Get EC2 costs via MCP service"""
        try:
            response = requests.post(
                f"{self.mcp_base_url}/get-hourly-cost",
                json={
                    "instance_type": instance_type,
                    "region": region,
                    "operating_system": operating_system
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"MCP EC2 cost service failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"MCP EC2 cost service error: {e}")
            raise Exception(f"EC2 cost estimation unavailable: {str(e)}")

# Global instance
mcp_cost_service = MCPCostService()