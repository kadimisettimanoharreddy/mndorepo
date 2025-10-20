import boto3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging
from .cost_config import CostConfig

logger = logging.getLogger(__name__)

class AWSCostService:
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.pricing_client = boto3.client('pricing', region_name='us-east-1')  # Pricing API only in us-east-1
        self.cost_client = boto3.client('ce', region_name='us-east-1')  # Cost Explorer only in us-east-1
        self.ec2_client = boto3.client('ec2', region_name=region)
    
    async def get_real_instance_pricing(self, instance_type: str, region: str = None) -> float:
        """Get real-time pricing from AWS Pricing API with caching"""
        try:
            if region is None:
                region = self.region
            
            # Check cache first
            cache_key = f"pricing_{instance_type}_{region}"
            cached_price = self._get_cached_price(cache_key)
            if cached_price is not None:
                return cached_price
            
            # Map region to pricing API location
            region_mapping = {
                'us-east-1': 'US East (N. Virginia)',
                'us-west-2': 'US West (Oregon)',
                'ap-south-1': 'Asia Pacific (Mumbai)',
                'eu-west-1': 'Europe (Ireland)'
            }
            
            location = region_mapping.get(region, 'US East (N. Virginia)')
            
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': location},
                    {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                    {'Type': 'TERM_MATCH', 'Field': 'operating-system', 'Value': 'Linux'}
                ]
            )
            
            if response['PriceList']:
                price_data = json.loads(response['PriceList'][0])
                terms = price_data['terms']['OnDemand']
                
                for term_key in terms:
                    price_dimensions = terms[term_key]['priceDimensions']
                    for dimension_key in price_dimensions:
                        price = float(price_dimensions[dimension_key]['pricePerUnit']['USD'])
                        # Cache the price
                        self._cache_price(cache_key, price)
                        return price
            
            fallback_price = self._get_fallback_pricing(instance_type)
            self._cache_price(cache_key, fallback_price)
            return fallback_price
            
        except Exception as e:
            logger.error(f"AWS Pricing API error: {str(e)}")
            fallback_price = self._get_fallback_pricing(instance_type)
            return fallback_price
    
    def _get_cached_price(self, cache_key: str) -> Optional[float]:
        """Get cached price if still valid"""
        try:
            import time
            cache_file = f"/tmp/{cache_key}.json"
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                # Check if cache is still valid (1 hour)
                if time.time() - cache_data['timestamp'] < 3600:
                    return cache_data['price']
        except Exception:
            pass
        return None
    
    def _cache_price(self, cache_key: str, price: float):
        """Cache price with timestamp"""
        try:
            import time
            cache_file = f"/tmp/{cache_key}.json"
            cache_data = {
                'price': price,
                'timestamp': time.time()
            }
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
        except Exception:
            pass
    
    def _get_fallback_pricing(self, instance_type: str) -> float:
        """Fallback pricing when API is unavailable"""
        return CostConfig.FALLBACK_PRICING.get(instance_type, 0.0104)

    
    async def get_actual_costs(self, instance_id: str) -> Dict:
        """Get actual costs from AWS Cost Explorer"""
        # Check if Cost Explorer is enabled
        if not CostConfig.ENABLE_COST_EXPLORER:
            logger.info("Cost Explorer disabled, returning empty actual costs")
            return {'total_30_days': 0, 'average_daily': 0, 'daily_breakdown': []}
            
        try:
            # Get instance tags to filter costs
            ec2_response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = ec2_response['Reservations'][0]['Instances'][0]
            
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=30)
            
            # Get costs for the last 30 days
            response = self.cost_client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_date.strftime('%Y-%m-%d'),
                    'End': end_date.strftime('%Y-%m-%d')
                },
                Granularity='DAILY',
                Metrics=['BlendedCost'],
                GroupBy=[
                    {'Type': 'DIMENSION', 'Key': 'SERVICE'}
                ],
                Filter={
                    'Dimensions': {
                        'Key': 'RESOURCE_ID',
                        'Values': [instance_id]
                    }
                }
            )
            
            total_cost = 0
            daily_costs = []
            
            for result in response['ResultsByTime']:
                date = result['TimePeriod']['Start']
                cost = 0
                
                for group in result['Groups']:
                    if 'Amazon Elastic Compute Cloud' in group['Keys'][0]:
                        cost += float(group['Metrics']['BlendedCost']['Amount'])
                
                daily_costs.append({'date': date, 'cost': cost})
                total_cost += cost
            
            return {
                'total_30_days': round(total_cost, 2),
                'average_daily': round(total_cost / 30, 2),
                'daily_breakdown': daily_costs[-7:]  # Last 7 days
            }
            
        except Exception as e:
            logger.error(f"Error fetching actual costs: {str(e)}")
            return {'total_30_days': 0, 'average_daily': 0, 'daily_breakdown': []}
    
    async def estimate_monthly_cost(self, instance_type: str, hours_per_day: int = 24) -> Dict:
        """Estimate monthly costs based on usage pattern"""
        try:
            hourly_rate = await self.get_real_instance_pricing(instance_type)
            
            daily_cost = hourly_rate * hours_per_day
            monthly_cost = hourly_rate * 720  # 720 hours per month (30 days * 24 hours)
            
            # Add storage costs (8GB default)
            storage_cost_per_gb = CostConfig.EBS_PRICING.get('gp2', 0.10)
            storage_cost = 8 * storage_cost_per_gb
            
            total_monthly = monthly_cost + storage_cost
            
            return {
                'compute_hourly': round(hourly_rate, 4),
                'compute_daily': round(daily_cost, 2),
                'compute_monthly': round(monthly_cost, 2),
                'storage_monthly': round(storage_cost, 2),
                'total_monthly': round(total_monthly, 2),
                'hours_per_day': hours_per_day,
                'currency': 'USD'
            }
            
        except Exception as e:
            logger.error(f"Error estimating costs: {str(e)}")
            return {
                'compute_hourly': 0.0104,
                'compute_daily': 0.25,
                'compute_monthly': 7.50,
                'storage_monthly': 0.80,
                'total_monthly': 8.30,
                'currency': 'USD'
            }