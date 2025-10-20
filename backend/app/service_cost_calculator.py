import logging
from typing import Dict

logger = logging.getLogger(__name__)

class ServiceCostCalculator:
    """Simple cost calculator for S3 and Lambda services"""
    
    @staticmethod
    def calculate_s3_cost(parameters: Dict) -> Dict:
        """Calculate S3 costs with fallback values"""
        try:
            storage_gb = parameters.get('storage_gb', 1)
            requests_per_month = parameters.get('requests_per_month', 1000)
            
            # S3 Standard pricing (fallback values)
            storage_cost = storage_gb * 0.023  # $0.023 per GB
            request_cost = (requests_per_month / 1000) * 0.0004  # $0.0004 per 1K requests
            
            return {
                'service_type': 's3',
                'storage_monthly': round(storage_cost, 4),
                'requests_monthly': round(request_cost, 4),
                'total_monthly': round(storage_cost + request_cost, 4),
                'currency': 'USD'
            }
        except Exception as e:
            logger.error(f"S3 cost calculation error: {e}")
            return {
                'service_type': 's3',
                'storage_monthly': 0.023,
                'requests_monthly': 0.0004,
                'total_monthly': 0.024,
                'currency': 'USD'
            }
    
    @staticmethod
    def calculate_lambda_cost(parameters: Dict) -> Dict:
        """Calculate Lambda costs with fallback values"""
        try:
            memory_mb = parameters.get('memory_mb', 128)
            monthly_requests = parameters.get('monthly_requests', 1000)
            avg_duration_ms = parameters.get('avg_duration_ms', 100)
            
            # Lambda pricing (fallback values)
            request_cost = (monthly_requests / 1000000) * 0.20  # $0.20 per 1M requests
            
            # Compute cost: $0.0000166667 per GB-second
            gb_seconds = (memory_mb / 1024) * (avg_duration_ms / 1000) * monthly_requests
            compute_cost = gb_seconds * 0.0000166667
            
            return {
                'service_type': 'lambda',
                'requests_monthly': round(request_cost, 6),
                'compute_monthly': round(compute_cost, 6),
                'total_monthly': round(request_cost + compute_cost, 6),
                'currency': 'USD'
            }
        except Exception as e:
            logger.error(f"Lambda cost calculation error: {e}")
            return {
                'service_type': 'lambda',
                'requests_monthly': 0.0002,
                'compute_monthly': 0.0001,
                'total_monthly': 0.0003,
                'currency': 'USD'
            }