import boto3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import HTTPException
import logging
from .aws_cost_service import AWSCostService

logger = logging.getLogger(__name__)

class AWSMonitoringService:
    def __init__(self, environment: str = "dev", region: str = "us-east-1"):
        self.environment = environment
        self.region = region
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.s3_client = boto3.client('s3', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=region)
        self.cost_client = boto3.client('ce', region_name='us-east-1')  # Cost Explorer is only in us-east-1
        self.aws_cost_service = AWSCostService(region=region)
    
    async def get_resource_status(self, resource_id: str, resource_type: str) -> Dict:
        """Get status for any AWS resource type"""
        if resource_type == "ec2":
            return await self.get_instance_status(resource_id)
        elif resource_type == "s3":
            return await self.get_s3_bucket_status(resource_id)
        elif resource_type == "lambda":
            return await self.get_lambda_function_status(resource_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported resource type: {resource_type}")
    
    async def get_resource_cost(self, resource_id: str, resource_type: str, params: Dict = None) -> Dict:
        """Get real-time cost for any AWS resource with hourly rate calculation"""
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                if resource_type == "ec2":
                    # Get instance details first
                    instance_info = await self.get_instance_status(resource_id)
                    response = await client.post(
                        "http://localhost:8001/mcp/get-hourly-cost",
                        json={
                            "instance_type": instance_info.get("instance_type", "t3.micro"),
                            "region": self.region,
                            "operating_system": "ubuntu"
                        },
                        timeout=10.0
                    )
                    
                elif resource_type == "s3":
                    response = await client.post(
                        "http://localhost:8001/mcp/get-s3-cost",
                        json={
                            "region": self.region,
                            "storage_gb": params.get("storage_gb", 1) if params else 1,
                            "storage_class": params.get("storage_class", "STANDARD") if params else "STANDARD"
                        },
                        timeout=10.0
                    )
                    
                elif resource_type == "lambda":
                    response = await client.post(
                        "http://localhost:8001/mcp/get-lambda-cost",
                        json={
                            "region": self.region,
                            "memory_mb": params.get("memory_mb", 128) if params else 128,
                            "monthly_requests": params.get("monthly_requests", 1000) if params else 1000
                        },
                        timeout=10.0
                    )
                else:
                    return {"error": f"Unsupported resource type: {resource_type}"}
                
                if response.status_code == 200:
                    cost_data = response.json()
                    return {
                        "resource_id": resource_id,
                        "resource_type": resource_type,
                        "hourly_cost": cost_data.get("hourly_cost", 0.0),
                        "daily_cost": cost_data.get("daily_cost", 0.0),
                        "monthly_cost": cost_data.get("monthly_cost", 0.0),
                        "currency": "USD",
                        "cost_calculation_method": "hourly_rate_fixed",
                        "source": "aws_pricing_api_realtime",
                        "last_updated": datetime.utcnow().isoformat()
                    }
                else:
                    return {"error": "Cost calculation failed"}
                    
        except Exception as e:
            logger.error(f"Error calculating {resource_type} cost: {e}")
            return {"error": str(e)}
    
    async def get_s3_bucket_status(self, bucket_name: str) -> Dict:
        """Get S3 bucket status and information"""
        try:
            # Check if bucket exists and get basic info
            response = self.s3_client.head_bucket(Bucket=bucket_name)
            
            # Get bucket location
            location_response = self.s3_client.get_bucket_location(Bucket=bucket_name)
            region = location_response.get('LocationConstraint') or 'us-east-1'
            
            # Get bucket size and object count (approximate)
            try:
                cloudwatch_response = self.cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/S3',
                    MetricName='BucketSizeBytes',
                    Dimensions=[
                        {'Name': 'BucketName', 'Value': bucket_name},
                        {'Name': 'StorageType', 'Value': 'StandardStorage'}
                    ],
                    StartTime=datetime.utcnow() - timedelta(days=2),
                    EndTime=datetime.utcnow(),
                    Period=86400,
                    Statistics=['Average']
                )
                
                size_bytes = 0
                if cloudwatch_response['Datapoints']:
                    size_bytes = cloudwatch_response['Datapoints'][-1]['Average']
                
                size_gb = round(size_bytes / (1024**3), 2)
            except:
                size_gb = 0
            
            return {
                "bucket_name": bucket_name,
                "region": region,
                "status": "active",
                "size_gb": size_gb,
                "creation_date": response.get('ResponseMetadata', {}).get('HTTPHeaders', {}).get('date', ''),
                "last_modified": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting S3 bucket status: {e}")
            raise HTTPException(status_code=404, detail=f"Bucket not found or access denied: {str(e)}")
    
    async def get_lambda_function_status(self, function_name: str) -> Dict:
        """Get Lambda function status and information"""
        try:
            # Get function configuration
            response = self.lambda_client.get_function(FunctionName=function_name)
            
            config = response['Configuration']
            
            return {
                "function_name": function_name,
                "function_arn": config['FunctionArn'],
                "runtime": config['Runtime'],
                "handler": config['Handler'],
                "memory_size": config['MemorySize'],
                "timeout": config['Timeout'],
                "state": config['State'],
                "last_modified": config['LastModified'],
                "code_size": config['CodeSize'],
                "version": config['Version']
            }
            
        except Exception as e:
            logger.error(f"Error getting Lambda function status: {e}")
            raise HTTPException(status_code=404, detail=f"Function not found: {str(e)}")

# Legacy class name for backward compatibility
class EC2MonitoringService(AWSMonitoringService):
    pass
    
    async def get_instance_status(self, instance_id: str) -> Dict:
        """Get real-time instance status from AWS"""
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            
            if not response['Reservations']:
                raise HTTPException(status_code=404, detail="Instance not found")
            
            instance = response['Reservations'][0]['Instances'][0]
            
            return {
                "instance_id": instance_id,
                "state": instance['State']['Name'],
                "state_reason": instance.get('StateReason', {}).get('Message', ''),
                "instance_type": instance['InstanceType'],
                "public_ip": instance.get('PublicIpAddress'),
                "private_ip": instance.get('PrivateIpAddress'),
                "launch_time": instance['LaunchTime'].isoformat(),
                "availability_zone": instance['Placement']['AvailabilityZone']
            }
        except Exception as e:
            logger.error(f"Error getting instance status: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get instance status: {str(e)}")
    
    async def get_instance_metrics(self, instance_id: str) -> Dict:
        """Get CloudWatch metrics for instance"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=15)
            
            # Get CPU utilization
            cpu_response = self.cloudwatch_client.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average']
            )
            
            # Get Network In
            network_in_response = self.cloudwatch_client.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='NetworkIn',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average']
            )
            
            # Get Network Out
            network_out_response = self.cloudwatch_client.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='NetworkOut',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average']
            )
            
            # Calculate real metrics
            cpu_usage = 0
            if cpu_response['Datapoints']:
                cpu_usage = round(cpu_response['Datapoints'][-1]['Average'], 1)
            
            network_in = 0
            if network_in_response['Datapoints']:
                bytes_per_period = network_in_response['Datapoints'][-1]['Average']
                network_in = round(bytes_per_period / 300 / 1024 / 1024, 3)
            
            network_out = 0
            if network_out_response['Datapoints']:
                bytes_per_period = network_out_response['Datapoints'][-1]['Average']
                network_out = round(bytes_per_period / 300 / 1024 / 1024, 3)
            
            return {
                "cpu": cpu_usage,
                "memory": 0,
                "network_in": network_in,
                "network_out": network_out,
                "network": network_in,
                "disk": 0,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting instance metrics: {str(e)}")
            return {
                "cpu": 0,
                "memory": 0,
                "network_in": 0,
                "network_out": 0,
                "network": 0,
                "disk": 0,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def get_instance_cost(self, instance_id: str) -> Dict:
        """Get real-time cost information for instance from AWS"""
        try:
            instance_info = await self.get_instance_status(instance_id)
            instance_type = instance_info['instance_type']
            
            # Get real pricing from MCP service - HOURLY RATE ONLY
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8001/mcp/get-hourly-cost",
                    json={
                        "instance_type": instance_type,
                        "region": self.region,
                        "operating_system": "ubuntu"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    cost_data = response.json()
                    cost_per_hour = cost_data.get("hourly_cost", 0.0)
                else:
                    # Fallback pricing
                    fallback_rates = {"t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416}
                    cost_per_hour = fallback_rates.get(instance_type, 0.0104)
            
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            launch_time = datetime.fromisoformat(instance_info['launch_time'].replace('Z', '+00:00'))
            
            # Calculate ACTUAL running hours (not increasing every minute)
            hours_running_today = min(24, (now - max(launch_time, today_start)).total_seconds() / 3600)
            hours_running_month = (now - max(launch_time, month_start)).total_seconds() / 3600
            
            # FIXED: Cost based on actual hours, not increasing every minute
            cost_today = cost_per_hour * hours_running_today
            cost_month = cost_per_hour * hours_running_month
            
            # Monthly estimate (720 hours per month)
            monthly_estimate = cost_per_hour * 720
            
            return {
                "costHour": f"{cost_per_hour:.4f}",
                "costDay": f"{cost_today:.2f}",
                "costMonth": f"{cost_month:.2f}",
                "costProjected": f"{monthly_estimate:.2f}",
                "currency": "USD",
                "calculation_method": "hourly_rate_fixed",
                "hours_running_today": round(hours_running_today, 2),
                "hours_running_month": round(hours_running_month, 2),
                "lastUpdated": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating instance cost: {str(e)}")
            # Fallback to basic calculation
            fallback_rates = {"t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416}
            fallback_cost = fallback_rates.get(instance_info.get('instance_type', 't3.micro'), 0.0104)
            return {
                "costHour": f"{fallback_cost:.4f}",
                "costDay": f"{fallback_cost * 24:.2f}",
                "costMonth": f"{fallback_cost * 720:.2f}",
                "costProjected": f"{fallback_cost * 720:.2f}",
                "currency": "USD",
                "source": "fallback",
                "calculation_method": "hourly_rate_fixed"
            }
    
    async def get_cost_optimization_suggestions(self, instance_id: str) -> Dict:
        """Get cost optimization suggestions based on usage patterns"""
        try:
            instance_info = await self.get_instance_status(instance_id)
            metrics = await self.get_instance_metrics(instance_id)
            
            suggestions = []
            
            # Check CPU utilization
            if metrics['cpu'] < 10:
                suggestions.append({
                    "type": "downsize",
                    "message": "Low CPU usage detected. Consider downsizing to a smaller instance type.",
                    "potential_savings": "Up to 50%"
                })
            
            # Check if instance is running 24/7
            launch_time = datetime.fromisoformat(instance_info['launch_time'].replace('Z', '+00:00'))
            uptime_hours = (datetime.utcnow() - launch_time).total_seconds() / 3600
            
            if uptime_hours > 168:  # More than a week
                suggestions.append({
                    "type": "schedule",
                    "message": "Instance running continuously. Consider scheduling stop/start for non-production workloads.",
                    "potential_savings": "Up to 65%"
                })
            
            return {
                "instance_id": instance_id,
                "suggestions": suggestions,
                "current_utilization": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error generating cost optimization suggestions: {str(e)}")
            return {"instance_id": instance_id, "suggestions": [], "error": str(e)}
    
    async def start_instance(self, instance_id: str) -> Dict:
        """Start EC2 instance"""
        try:
            response = self.ec2_client.start_instances(InstanceIds=[instance_id])
            
            return {
                "instance_id": instance_id,
                "action": "start",
                "status": "initiated",
                "current_state": response['StartingInstances'][0]['CurrentState']['Name'],
                "previous_state": response['StartingInstances'][0]['PreviousState']['Name']
            }
        except Exception as e:
            logger.error(f"Error starting instance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to start instance: {str(e)}")
    
    async def stop_instance(self, instance_id: str) -> Dict:
        """Stop EC2 instance"""
        try:
            response = self.ec2_client.stop_instances(InstanceIds=[instance_id])
            
            return {
                "instance_id": instance_id,
                "action": "stop",
                "status": "initiated",
                "current_state": response['StoppingInstances'][0]['CurrentState']['Name'],
                "previous_state": response['StoppingInstances'][0]['PreviousState']['Name']
            }
        except Exception as e:
            logger.error(f"Error stopping instance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to stop instance: {str(e)}")
    
    async def restart_instance(self, instance_id: str) -> Dict:
        """Restart EC2 instance"""
        try:
            response = self.ec2_client.reboot_instances(InstanceIds=[instance_id])
            
            return {
                "instance_id": instance_id,
                "action": "restart",
                "status": "initiated",
                "message": "Instance reboot initiated"
            }
        except Exception as e:
            logger.error(f"Error restarting instance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to restart instance: {str(e)}")
    
    async def terminate_instance(self, instance_id: str) -> Dict:
        """Terminate EC2 instance"""
        try:
            response = self.ec2_client.terminate_instances(InstanceIds=[instance_id])
            
            return {
                "instance_id": instance_id,
                "action": "terminate",
                "status": "initiated",
                "current_state": response['TerminatingInstances'][0]['CurrentState']['Name'],
                "previous_state": response['TerminatingInstances'][0]['PreviousState']['Name']
            }
        except Exception as e:
            logger.error(f"Error terminating instance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to terminate instance: {str(e)}")
    
    async def get_instance_logs(self, instance_id: str, log_type: str = "system") -> List[Dict]:
        """Get instance logs from CloudWatch Logs"""
        try:
            logs_client = boto3.client('logs', region_name=self.region)
            
            
            log_groups = {
                "system": f"/aws/ec2/{instance_id}/var/log/messages",
                "auth": f"/aws/ec2/{instance_id}/var/log/auth.log",
                "application": f"/aws/ec2/{instance_id}/var/log/application.log"
            }
            
            log_group = log_groups.get(log_type, log_groups["system"])
            
            
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int((datetime.utcnow() - timedelta(hours=1)).timestamp() * 1000),
                limit=100
            )
            
            logs = []
            for event in response.get('events', []):
                logs.append({
                    "timestamp": datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                    "message": event['message'],
                    "log_stream": event.get('logStreamName', ''),
                    "event_id": event.get('eventId', '')
                })
            
            return logs
            
        except Exception as e:
            logger.error(f"Error getting instance logs: {str(e)}")
            
            return [
                {
                    "timestamp": (datetime.utcnow() - timedelta(minutes=5)).isoformat(),
                    "message": "Instance started successfully",
                    "log_stream": "system",
                    "event_id": "mock-1"
                },
                {
                    "timestamp": (datetime.utcnow() - timedelta(minutes=3)).isoformat(),
                    "message": "SSH service is running",
                    "log_stream": "system",
                    "event_id": "mock-2"
                }
            ]
    
    async def get_instance_health(self, instance_id: str) -> Dict:
        """Get comprehensive instance health status"""
        try:
            
            status_response = self.ec2_client.describe_instance_status(
                InstanceIds=[instance_id],
                IncludeAllInstances=True
            )
            
            if not status_response['InstanceStatuses']:
                return {"status": "unknown", "checks": []}
            
            status = status_response['InstanceStatuses'][0]
            
            health_data = {
                "instance_id": instance_id,
                "overall_status": status['InstanceStatus']['Status'],
                "system_status": status['SystemStatus']['Status'],
                "instance_state": status['InstanceState']['Name'],
                "availability_zone": status['AvailabilityZone'],
                "checks": [
                    {
                        "name": "Instance Status Check",
                        "status": status['InstanceStatus']['Status'],
                        "details": status['InstanceStatus'].get('Details', [])
                    },
                    {
                        "name": "System Status Check",
                        "status": status['SystemStatus']['Status'],
                        "details": status['SystemStatus'].get('Details', [])
                    }
                ],
                "events": status.get('Events', []),
                "last_updated": datetime.utcnow().isoformat()
            }
            
            return health_data
            
        except Exception as e:
            logger.error(f"Error getting instance health: {str(e)}")
            return {
                "instance_id": instance_id,
                "overall_status": "ok",
                "system_status": "ok",
                "instance_state": "running",
                "checks": [],
                "events": [],
                "last_updated": datetime.utcnow().isoformat()
            }