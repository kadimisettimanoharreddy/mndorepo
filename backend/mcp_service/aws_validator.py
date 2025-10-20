#!/usr/bin/env python3
"""
AWS Credentials Validator for MCP Service
"""

import os
import boto3
import logging
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

logger = logging.getLogger(__name__)

class AWSValidator:
    def __init__(self):
        self.credentials_valid = False
        self.error_message = None
        self.regions_tested = []
        
    def validate_credentials(self) -> dict:
        """Validate AWS credentials and return status"""
        
        # Check if credentials are set
        aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        
        if not aws_access_key or not aws_secret_key:
            return {
                "valid": False,
                "error": "missing_credentials",
                "message": "AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY not set in environment",
                "suggestion": "Set AWS credentials in environment variables"
            }
        
        # Test credentials with STS
        try:
            sts_client = boto3.client(
                'sts',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name='us-east-1'
            )
            
            # Get caller identity to validate credentials
            identity = sts_client.get_caller_identity()
            
            self.credentials_valid = True
            
            return {
                "valid": True,
                "account_id": identity.get('Account'),
                "user_id": identity.get('UserId'),
                "arn": identity.get('Arn'),
                "message": "AWS credentials are valid"
            }
            
        except NoCredentialsError:
            return {
                "valid": False,
                "error": "no_credentials",
                "message": "No AWS credentials found"
            }
        except PartialCredentialsError:
            return {
                "valid": False,
                "error": "partial_credentials", 
                "message": "Incomplete AWS credentials"
            }
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidUserID.NotFound':
                return {
                    "valid": False,
                    "error": "invalid_credentials",
                    "message": "AWS credentials are invalid"
                }
            elif error_code == 'AccessDenied':
                return {
                    "valid": False,
                    "error": "access_denied",
                    "message": "AWS credentials valid but access denied for STS"
                }
            else:
                return {
                    "valid": False,
                    "error": "aws_error",
                    "message": f"AWS error: {error_code}"
                }
        except Exception as e:
            return {
                "valid": False,
                "error": "unknown_error",
                "message": f"Unknown error: {str(e)}"
            }
    
    def test_ec2_access(self, region: str = 'us-east-1') -> dict:
        """Test EC2 access in specific region"""
        try:
            ec2_client = boto3.client(
                'ec2',
                region_name=region,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            
            # Test describe_regions (minimal permission needed)
            response = ec2_client.describe_regions(RegionNames=[region])
            
            if response['Regions']:
                return {
                    "valid": True,
                    "region": region,
                    "message": f"EC2 access valid in {region}"
                }
            else:
                return {
                    "valid": False,
                    "region": region,
                    "error": "region_not_found",
                    "message": f"Region {region} not found"
                }
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            return {
                "valid": False,
                "region": region,
                "error": error_code,
                "message": f"EC2 access error in {region}: {error_code}"
            }
        except Exception as e:
            return {
                "valid": False,
                "region": region,
                "error": "unknown_error",
                "message": f"Unknown EC2 error: {str(e)}"
            }
    
    def test_pricing_access(self) -> dict:
        """Test AWS Pricing API access"""
        try:
            pricing_client = boto3.client(
                'pricing',
                region_name='us-east-1',  # Pricing API only available in us-east-1
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            
            # Test with minimal request
            response = pricing_client.get_products(
                ServiceCode='AmazonEC2',
                MaxResults=1
            )
            
            if response.get('PriceList'):
                return {
                    "valid": True,
                    "message": "Pricing API access valid"
                }
            else:
                return {
                    "valid": False,
                    "error": "no_pricing_data",
                    "message": "No pricing data returned"
                }
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            return {
                "valid": False,
                "error": error_code,
                "message": f"Pricing API error: {error_code}"
            }
        except Exception as e:
            return {
                "valid": False,
                "error": "unknown_error",
                "message": f"Pricing API unknown error: {str(e)}"
            }
    
    def comprehensive_validation(self) -> dict:
        """Run comprehensive AWS validation"""
        
        results = {
            "overall_valid": False,
            "credentials": {},
            "ec2_access": {},
            "pricing_access": {},
            "recommendations": []
        }
        
        # Test credentials
        cred_result = self.validate_credentials()
        results["credentials"] = cred_result
        
        if not cred_result["valid"]:
            results["recommendations"].append("Fix AWS credentials first")
            return results
        
        # Test EC2 access
        ec2_result = self.test_ec2_access()
        results["ec2_access"] = ec2_result
        
        # Test Pricing access
        pricing_result = self.test_pricing_access()
        results["pricing_access"] = pricing_result
        
        # Determine overall status
        if cred_result["valid"] and ec2_result["valid"]:
            results["overall_valid"] = True
            
            if not pricing_result["valid"]:
                results["recommendations"].append("Pricing API access limited - cost calculations may not work")
        else:
            results["recommendations"].append("EC2 access required for AMI lookups")
        
        return results

def main():
    """Test AWS validation"""
    validator = AWSValidator()
    
    print("🔍 AWS Credentials Validation")
    print("=" * 40)
    
    # Run comprehensive validation
    results = validator.comprehensive_validation()
    
    print(f"Overall Valid: {results['overall_valid']}")
    print(f"Credentials: {results['credentials'].get('valid', False)} - {results['credentials'].get('message', 'N/A')}")
    print(f"EC2 Access: {results['ec2_access'].get('valid', False)} - {results['ec2_access'].get('message', 'N/A')}")
    print(f"Pricing Access: {results['pricing_access'].get('valid', False)} - {results['pricing_access'].get('message', 'N/A')}")
    
    if results['recommendations']:
        print("\nRecommendations:")
        for rec in results['recommendations']:
            print(f"  - {rec}")
    
    return results['overall_valid']

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)