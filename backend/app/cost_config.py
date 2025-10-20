"""
Cost monitoring configuration
"""
import os
from typing import Dict, Any

class CostConfig:
    """Configuration for cost monitoring features"""
    
    # Enable/disable real AWS cost fetching
    ENABLE_REAL_AWS_PRICING = os.getenv('ENABLE_REAL_AWS_PRICING', 'true').lower() == 'true'
    
    # Enable/disable Cost Explorer integration
    ENABLE_COST_EXPLORER = os.getenv('ENABLE_COST_EXPLORER', 'true').lower() == 'true'
    
    # Cache pricing data for this many seconds
    PRICING_CACHE_TTL = int(os.getenv('PRICING_CACHE_TTL', '3600'))  # 1 hour
    
    # Default region for pricing
    DEFAULT_PRICING_REGION = os.getenv('DEFAULT_PRICING_REGION', 'us-east-1')
    
    # Fallback pricing when AWS APIs are unavailable
    FALLBACK_PRICING = {
        # T3 instances
        't3.nano': 0.0052,
        't3.micro': 0.0104,
        't3.small': 0.0208,
        't3.medium': 0.0416,
        't3.large': 0.0832,
        't3.xlarge': 0.1664,
        't3.2xlarge': 0.3328,
        
        # T2 instances
        't2.nano': 0.0058,
        't2.micro': 0.0116,
        't2.small': 0.023,
        't2.medium': 0.046,
        't2.large': 0.092,
        
        # M5 instances
        'm5.large': 0.096,
        'm5.xlarge': 0.192,
        'm5.2xlarge': 0.384,
        'm5.4xlarge': 0.768,
        
        # C5 instances
        'c5.large': 0.085,
        'c5.xlarge': 0.17,
        'c5.2xlarge': 0.34,
        'c5.4xlarge': 0.68,
        
        # R5 instances
        'r5.large': 0.126,
        'r5.xlarge': 0.252,
        'r5.2xlarge': 0.504
    }
    
    # EBS pricing per GB per month
    EBS_PRICING = {
        'gp2': 0.10,  # General Purpose SSD
        'gp3': 0.08,  # General Purpose SSD (newer)
        'io1': 0.125, # Provisioned IOPS SSD
        'io2': 0.125, # Provisioned IOPS SSD (newer)
        'st1': 0.045, # Throughput Optimized HDD
        'sc1': 0.025  # Cold HDD
    }
    
    @classmethod
    def get_config_summary(cls) -> Dict[str, Any]:
        """Get current configuration summary"""
        return {
            'real_aws_pricing_enabled': cls.ENABLE_REAL_AWS_PRICING,
            'cost_explorer_enabled': cls.ENABLE_COST_EXPLORER,
            'pricing_cache_ttl': cls.PRICING_CACHE_TTL,
            'default_region': cls.DEFAULT_PRICING_REGION,
            'fallback_instance_types': len(cls.FALLBACK_PRICING),
            'ebs_types_supported': len(cls.EBS_PRICING)
        }