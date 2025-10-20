import boto3
import botocore
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Set
import logging

logger = logging.getLogger(__name__)

DEFAULT_THREAD_POOL = ThreadPoolExecutor(max_workers=8)

class AWSResourceFetcher:
    def __init__(self, environment: Optional[str], region: Optional[str] = "us-east-1"):
        self.environment = (environment or "dev").lower().strip()
        self.region = (region or "us-east-1").strip()
        self.session = boto3.Session(region_name=self.region)
        self._boto3_clients: Dict[str, Any] = {}
        self.credentials_ok = False
        self.account_id: Optional[str] = None
        try:
            self._validate_credentials_sync()
        except Exception:
            pass

    def _get_client(self, service_name: str):
        key = f"{service_name}:{self.region}"
        if key not in self._boto3_clients:
            self._boto3_clients[key] = self.session.client(service_name, region_name=self.region)
        return self._boto3_clients[key]

    def _validate_credentials_sync(self):
        sts = self._get_client("sts")
        resp = sts.get_caller_identity()
        self.account_id = resp.get("Account")
        self.credentials_ok = True
        return {"ok": True, "account": self.account_id}

    async def _run_in_executor(self, fn, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(DEFAULT_THREAD_POOL, lambda: fn(*args, **kwargs))

    async def _safe_call(self, label: str, fn):
        try:
            return await self._run_in_executor(fn)
        except (botocore.exceptions.NoCredentialsError,
                botocore.exceptions.EndpointConnectionError,
                botocore.exceptions.ClientError,
                botocore.exceptions.BotoCoreError,
                Exception):
            return []

    def _get_default_vpc_ids_sync(self) -> Set[str]:
        ec2 = self._get_client("ec2")
        resp = ec2.describe_vpcs()
        default_ids = set()
        for v in resp.get("Vpcs", []):
            if v.get("IsDefault", False):
                vid = v.get("VpcId")
                if vid:
                    default_ids.add(vid)
        return default_ids

    async def _get_default_vpc_ids(self) -> Set[str]:
        return await self._run_in_executor(self._get_default_vpc_ids_sync)

    async def get_vpcs(self, existing_only: bool = False) -> List[Dict[str, Any]]:
        def _fn():
            ec2 = self._get_client("ec2")
            paginator = ec2.get_paginator("describe_vpcs")
            out = []
            for page in paginator.paginate():
                for v in page.get("Vpcs", []):
                    is_default = v.get("IsDefault", False)
                    if existing_only and is_default:
                        continue
                    name = next((t["Value"] for t in (v.get("Tags") or []) if t.get("Key") == "Name"), v.get("VpcId"))
                    out.append({
                        "id": v.get("VpcId", ""),
                        "name": name,
                        "cidr": v.get("CidrBlock", ""),
                        "is_default": is_default,
                    })
            return out
        return await self._safe_call("VPCs", _fn)

    async def get_subnets(self, vpc_id: Optional[str] = None, existing_only: bool = False) -> List[Dict[str, Any]]:
        def _fn(default_vpc_ids: Set[str]):
            ec2 = self._get_client("ec2")
            if vpc_id:
                r = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
            else:
                r = ec2.describe_subnets()
            out = []
            for s in r.get("Subnets", []):
                sid = s.get("SubnetId")
                svpc = s.get("VpcId")
                if existing_only and svpc and svpc in default_vpc_ids:
                    continue
                name = next((t["Value"] for t in (s.get("Tags") or []) if t.get("Key") == "Name"), s.get("SubnetId"))
                out.append({
                    "id": sid or "",
                    "name": name,
                    "cidr": s.get("CidrBlock", ""),
                    "vpc_id": svpc or "",
                    "availability_zone": s.get("AvailabilityZone", ""),
                    "public": s.get("MapPublicIpOnLaunch", False),
                })
            return out

        if existing_only:
            default_vpc_ids = await self._get_default_vpc_ids()
            return await self._safe_call("Subnets", lambda: _fn(default_vpc_ids))
        else:
            return await self._safe_call("Subnets", lambda: _fn(set()))

    async def get_security_groups(self, vpc_id: Optional[str] = None, existing_only: bool = False) -> List[Dict[str, Any]]:
        def _fn(default_vpc_ids: Set[str]):
            ec2 = self._get_client("ec2")
            if vpc_id:
                r = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
            else:
                r = ec2.describe_security_groups()
            out = []
            for g in r.get("SecurityGroups", []):
                gid = g.get("GroupId", "")
                gname = g.get("GroupName", "")
                gvpc = g.get("VpcId", "")
                if existing_only:
                    if (gname and gname.lower() == "default") or (gvpc and gvpc in default_vpc_ids):
                        continue
                out.append({
                    "id": gid,
                    "name": gname,
                    "description": g.get("Description", ""),
                    "vpc_id": gvpc,
                })
            return out

        if existing_only:
            default_vpc_ids = await self._get_default_vpc_ids()
            return await self._safe_call("SecurityGroups", lambda: _fn(default_vpc_ids))
        else:
            return await self._safe_call("SecurityGroups", lambda: _fn(set()))

    async def get_vpc_by_id(self, vpc_id: str) -> Optional[Dict[str, Any]]:
        def _fn():
            ec2 = self._get_client("ec2")
            r = ec2.describe_vpcs(VpcIds=[vpc_id])
            vs = r.get("Vpcs", [])
            if not vs:
                return None
            v = vs[0]
            name = next((t["Value"] for t in (v.get("Tags") or []) if t.get("Key") == "Name"), v.get("VpcId"))
            return {
                "id": v.get("VpcId", ""),
                "name": name,
                "cidr": v.get("CidrBlock", ""),
                "is_default": v.get("IsDefault", False)
            }
        return await self._safe_call("GetVPCById", _fn)

    async def get_subnet_by_id(self, subnet_id: str) -> Optional[Dict[str, Any]]:
        def _fn():
            ec2 = self._get_client("ec2")
            r = ec2.describe_subnets(SubnetIds=[subnet_id])
            subs = r.get("Subnets", [])
            if not subs:
                return None
            s = subs[0]
            name = next((t["Value"] for t in (s.get("Tags") or []) if t.get("Key") == "Name"), s.get("SubnetId"))
            return {
                "id": s.get("SubnetId", ""),
                "name": name,
                "cidr": s.get("CidrBlock", ""),
                "vpc_id": s.get("VpcId", ""),
                "availability_zone": s.get("AvailabilityZone", ""),
                "public": s.get("MapPublicIpOnLaunch", False)
            }
        return await self._safe_call("GetSubnetById", _fn)

    async def get_security_group_rules(self, sg_id: str) -> Optional[Dict[str, Any]]:
        def _fn():
            ec2 = self._get_client("ec2")
            r = ec2.describe_security_groups(GroupIds=[sg_id])
            gs = r.get("SecurityGroups", [])
            if not gs:
                return None
            g = gs[0]
            
            def normalize_rules(rules):
                out = []
                for rule in rules:
                    ranges = []
                    ranges.extend([x.get("CidrIp") for x in rule.get("IpRanges", []) if x.get("CidrIp")])
                    ranges.extend([x.get("CidrIpv6") for x in rule.get("Ipv6Ranges", []) if x.get("CidrIpv6")])
                    ranges.extend([ug.get("GroupId") for ug in rule.get("UserIdGroupPairs", []) if ug.get("GroupId")])
                    
                    out.append({
                        "protocol": rule.get("IpProtocol"),
                        "from_port": rule.get("FromPort"),
                        "to_port": rule.get("ToPort"),
                        "ranges": ranges,
                    })
                return out
            
            return {
                "ingress": normalize_rules(g.get("IpPermissions", [])),
                "egress": normalize_rules(g.get("IpPermissionsEgress", []))
            }
        
        return await self._safe_call("GetSGRules", _fn)

    # ================================================================
    # NEW KEYPAIR METHODS - ADDED FOR ENHANCED FUNCTIONALITY
    # ================================================================

    async def get_keypairs(self) -> List[Dict[str, Any]]:
        """Fetch keypairs from user's specific region - ENHANCED VERSION"""
        def _fn():
            # Make sure we use the correct region from self.region
            ec2 = self._get_client("ec2")  # This should use self.region
            logger.info(f"Fetching keypairs from region: {self.region}")
            
            try:
                # Use describe_key_pairs with proper error handling
                response = ec2.describe_key_pairs()
                keypairs = []
                
                for kp in response.get("KeyPairs", []):
                    keypairs.append({
                        "name": kp.get("KeyName", ""),
                        "fingerprint": kp.get("KeyFingerprint", ""),
                        "type": kp.get("KeyType", "rsa"),
                        "created": str(kp.get("CreateTime", ""))
                    })
                
                logger.info(f"Found {len(keypairs)} keypairs in region {self.region}")
                return keypairs
                
            except Exception as e:
                logger.error(f"Error fetching keypairs from region {self.region}: {e}")
                return []
        
        return await self._safe_call("Keypairs", _fn)

    async def check_keypair_exists(self, keypair_name: str) -> bool:
        """Check if keypair exists in user's specific region - ENHANCED VERSION"""
        def _fn():
            ec2 = self._get_client("ec2")  # Uses self.region
            logger.info(f"Checking if keypair '{keypair_name}' exists in region {self.region}")
            
            try:
                response = ec2.describe_key_pairs(KeyNames=[keypair_name])
                exists = len(response.get("KeyPairs", [])) > 0
                logger.info(f"Keypair '{keypair_name}' exists in {self.region}: {exists}")
                return exists
            except Exception as e:
                logger.debug(f"Keypair '{keypair_name}' not found in {self.region}: {e}")
                return False
        
        return await self._safe_call("CheckKeypair", _fn)

    async def get_keypair_by_name(self, keypair_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific keypair - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            logger.info(f"Fetching details for keypair '{keypair_name}' in region {self.region}")
            
            try:
                response = ec2.describe_key_pairs(KeyNames=[keypair_name])
                keypairs = response.get("KeyPairs", [])
                
                if not keypairs:
                    return None
                
                kp = keypairs[0]
                return {
                    "name": kp.get("KeyName", ""),
                    "fingerprint": kp.get("KeyFingerprint", ""),
                    "type": kp.get("KeyType", "rsa"),
                    "created": str(kp.get("CreateTime", "")),
                    "key_id": kp.get("KeyPairId", ""),
                    "tags": kp.get("Tags", [])
                }
                
            except Exception as e:
                logger.debug(f"Error fetching keypair '{keypair_name}' details: {e}")
                return None
        
        return await self._safe_call("GetKeypairDetails", _fn)
    
    async def get_vpc_details(self, vpc_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific VPC - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            logger.info(f"Fetching details for VPC '{vpc_id}' in region {self.region}")
            
            try:
                response = ec2.describe_vpcs(VpcIds=[vpc_id])
                vpcs = response.get("Vpcs", [])
                
                if not vpcs:
                    return None
                
                vpc = vpcs[0]
                name = next((t["Value"] for t in (vpc.get("Tags") or []) if t.get("Key") == "Name"), vpc.get("VpcId"))
                
                return {
                    "id": vpc.get("VpcId", ""),
                    "name": name,
                    "cidr": vpc.get("CidrBlock", ""),
                    "is_default": vpc.get("IsDefault", False),
                    "state": vpc.get("State", ""),
                    "dhcp_options_id": vpc.get("DhcpOptionsId", ""),
                    "tags": vpc.get("Tags", [])
                }
                
            except Exception as e:
                logger.debug(f"Error fetching VPC '{vpc_id}' details: {e}")
                return None
        
        return await self._safe_call("GetVPCDetails", _fn)
    
    async def get_subnet_details(self, subnet_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific subnet - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            logger.info(f"Fetching details for subnet '{subnet_id}' in region {self.region}")
            
            try:
                response = ec2.describe_subnets(SubnetIds=[subnet_id])
                subnets = response.get("Subnets", [])
                
                if not subnets:
                    return None
                
                subnet = subnets[0]
                name = next((t["Value"] for t in (subnet.get("Tags") or []) if t.get("Key") == "Name"), subnet.get("SubnetId"))
                
                return {
                    "id": subnet.get("SubnetId", ""),
                    "name": name,
                    "cidr": subnet.get("CidrBlock", ""),
                    "vpc_id": subnet.get("VpcId", ""),
                    "availability_zone": subnet.get("AvailabilityZone", ""),
                    "public": subnet.get("MapPublicIpOnLaunch", False),
                    "state": subnet.get("State", ""),
                    "available_ip_count": subnet.get("AvailableIpAddressCount", 0),
                    "tags": subnet.get("Tags", [])
                }
                
            except Exception as e:
                logger.debug(f"Error fetching subnet '{subnet_id}' details: {e}")
                return None
        
        return await self._safe_call("GetSubnetDetails", _fn)
    
    async def get_security_group_details(self, sg_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific security group - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            logger.info(f"Fetching details for security group '{sg_id}' in region {self.region}")
            
            try:
                response = ec2.describe_security_groups(GroupIds=[sg_id])
                sgs = response.get("SecurityGroups", [])
                
                if not sgs:
                    return None
                
                sg = sgs[0]
                
                return {
                    "id": sg.get("GroupId", ""),
                    "name": sg.get("GroupName", ""),
                    "description": sg.get("Description", ""),
                    "vpc_id": sg.get("VpcId", ""),
                    "owner_id": sg.get("OwnerId", ""),
                    "ingress_rules": sg.get("IpPermissions", []),
                    "egress_rules": sg.get("IpPermissionsEgress", []),
                    "tags": sg.get("Tags", [])
                }
                
            except Exception as e:
                logger.debug(f"Error fetching security group '{sg_id}' details: {e}")
                return None
        
        return await self._safe_call("GetSGDetails", _fn)

    async def validate_keypair_region_access(self, keypair_name: str) -> Dict[str, Any]:
        """Validate keypair access and provide detailed status - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            
            try:
                # Try to describe the specific keypair
                response = ec2.describe_key_pairs(KeyNames=[keypair_name])
                keypairs = response.get("KeyPairs", [])
                
                if keypairs:
                    kp = keypairs[0]
                    return {
                        "exists": True,
                        "accessible": True,
                        "region": self.region,
                        "name": kp.get("KeyName", ""),
                        "type": kp.get("KeyType", "rsa"),
                        "message": f"Keypair '{keypair_name}' found and accessible in {self.region}"
                    }
                else:
                    return {
                        "exists": False,
                        "accessible": False,
                        "region": self.region,
                        "name": keypair_name,
                        "message": f"Keypair '{keypair_name}' not found in {self.region}"
                    }
                    
            except botocore.exceptions.ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                
                if error_code == "InvalidKeyPair.NotFound":
                    return {
                        "exists": False,
                        "accessible": False,
                        "region": self.region,
                        "name": keypair_name,
                        "message": f"Keypair '{keypair_name}' does not exist in {self.region}"
                    }
                elif error_code in ["UnauthorizedOperation", "AccessDenied"]:
                    return {
                        "exists": None,
                        "accessible": False,
                        "region": self.region,
                        "name": keypair_name,
                        "message": f"Access denied when checking keypair '{keypair_name}' in {self.region}"
                    }
                else:
                    return {
                        "exists": None,
                        "accessible": False,
                        "region": self.region,
                        "name": keypair_name,
                        "message": f"Error checking keypair '{keypair_name}': {str(e)}"
                    }
                    
            except Exception as e:
                return {
                    "exists": None,
                    "accessible": False,
                    "region": self.region,
                    "name": keypair_name,
                    "message": f"Unexpected error checking keypair '{keypair_name}': {str(e)}"
                }
        
        return await self._safe_call("ValidateKeypairAccess", _fn)

    async def get_keypairs_with_filters(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get keypairs with optional filtering - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            logger.info(f"Fetching filtered keypairs from region: {self.region}")
            
            try:
                kwargs = {}
                if filters:
                    # Convert filters to AWS format if needed
                    aws_filters = []
                    for key, value in filters.items():
                        if key == "key_name":
                            aws_filters.append({"Name": "key-name", "Values": [value] if isinstance(value, str) else value})
                        elif key == "fingerprint":
                            aws_filters.append({"Name": "fingerprint", "Values": [value] if isinstance(value, str) else value})
                    
                    if aws_filters:
                        kwargs["Filters"] = aws_filters
                
                response = ec2.describe_key_pairs(**kwargs)
                keypairs = []
                
                for kp in response.get("KeyPairs", []):
                    keypair_data = {
                        "name": kp.get("KeyName", ""),
                        "fingerprint": kp.get("KeyFingerprint", ""),
                        "type": kp.get("KeyType", "rsa"),
                        "created": str(kp.get("CreateTime", "")),
                        "key_id": kp.get("KeyPairId", "")
                    }
                    
                    # Add tags if present
                    if kp.get("Tags"):
                        keypair_data["tags"] = {tag.get("Key", ""): tag.get("Value", "") for tag in kp.get("Tags", [])}
                    
                    keypairs.append(keypair_data)
                
                logger.info(f"Found {len(keypairs)} filtered keypairs in region {self.region}")
                return keypairs
                
            except Exception as e:
                logger.error(f"Error fetching filtered keypairs from region {self.region}: {e}")
                return []
        
        return await self._safe_call("FilteredKeypairs", _fn)

    async def test_keypair_connectivity(self, keypair_name: str) -> Dict[str, Any]:
        """Test if keypair can be used for EC2 operations - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            
            try:
                # First check if keypair exists
                response = ec2.describe_key_pairs(KeyNames=[keypair_name])
                keypairs = response.get("KeyPairs", [])
                
                if not keypairs:
                    return {
                        "status": "not_found",
                        "message": f"Keypair '{keypair_name}' not found in {self.region}",
                        "usable": False
                    }
                
                kp = keypairs[0]
                
                # Additional validation checks could go here
                # For now, if we can describe it, it's likely usable
                return {
                    "status": "accessible",
                    "message": f"Keypair '{keypair_name}' is accessible and appears usable",
                    "usable": True,
                    "details": {
                        "name": kp.get("KeyName", ""),
                        "type": kp.get("KeyType", "rsa"),
                        "fingerprint": kp.get("KeyFingerprint", "")[:20] + "..." if kp.get("KeyFingerprint") else "",
                        "region": self.region
                    }
                }
                
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Error testing keypair '{keypair_name}': {str(e)}",
                    "usable": False
                }
        
        return await self._safe_call("TestKeypairConnectivity", _fn)

    # ================================================================
    # ENHANCED ERROR HANDLING AND LOGGING - NEW METHODS
    # ================================================================

    async def get_region_info(self) -> Dict[str, Any]:
        """Get information about the current region - NEW METHOD"""
        def _fn():
            ec2 = self._get_client("ec2")
            
            try:
                # Get region information
                response = ec2.describe_regions(RegionNames=[self.region])
                regions = response.get("Regions", [])
                
                if regions:
                    region_info = regions[0]
                    return {
                        "region_name": region_info.get("RegionName", self.region),
                        "endpoint": region_info.get("Endpoint", ""),
                        "opt_in_status": region_info.get("OptInStatus", "opt-in-not-required"),
                        "accessible": True
                    }
                else:
                    return {
                        "region_name": self.region,
                        "accessible": False,
                        "error": f"Region {self.region} not found or not accessible"
                    }
                    
            except Exception as e:
                return {
                    "region_name": self.region,
                    "accessible": False,
                    "error": f"Error accessing region {self.region}: {str(e)}"
                }
        
        return await self._safe_call("GetRegionInfo", _fn)

    async def validate_credentials_and_permissions(self) -> Dict[str, Any]:
        """Comprehensive validation of AWS credentials and permissions - NEW METHOD"""
        def _fn():
            try:
                # Test STS access
                sts = self._get_client("sts")
                identity = sts.get_caller_identity()
                
                # Test EC2 access
                ec2 = self._get_client("ec2")
                ec2.describe_availability_zones()  # Minimal call to test permissions
                
                return {
                    "valid": True,
                    "account_id": identity.get("Account"),
                    "user_id": identity.get("UserId"),
                    "arn": identity.get("Arn"),
                    "region": self.region,
                    "ec2_access": True,
                    "message": f"Credentials valid for account {identity.get('Account')} in region {self.region}"
                }
                
            except botocore.exceptions.NoCredentialsError:
                return {
                    "valid": False,
                    "error": "no_credentials",
                    "message": "No AWS credentials found"
                }
            except botocore.exceptions.ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                return {
                    "valid": False,
                    "error": error_code,
                    "message": f"AWS API error: {str(e)}"
                }
            except Exception as e:
                return {
                    "valid": False,
                    "error": "unknown",
                    "message": f"Unexpected error: {str(e)}"
                }
        
        return await self._safe_call("ValidateCredentials", _fn)

    # ================================================================
    # UTILITY METHODS FOR ENHANCED FUNCTIONALITY
    # ================================================================

    def get_current_region(self) -> str:
        """Get the current region being used"""
        return self.region

    def get_current_environment(self) -> str:
        """Get the current environment being used"""
        return self.environment

    async def health_check(self) -> Dict[str, Any]:
        """Perform a health check of AWS connectivity - NEW METHOD"""
        try:
            # Quick validation
            validation = await self.validate_credentials_and_permissions()
            
            if not validation.get("valid"):
                return {
                    "healthy": False,
                    "region": self.region,
                    "environment": self.environment,
                    "error": validation.get("message", "Unknown error")
                }
            
            # Test basic EC2 functionality
            def _test_ec2():
                ec2 = self._get_client("ec2")
                # Quick call that requires minimal permissions
                ec2.describe_availability_zones()
                return True
            
            ec2_ok = await self._safe_call("HealthCheckEC2", _test_ec2)
            
            return {
                "healthy": bool(ec2_ok),
                "region": self.region,
                "environment": self.environment,
                "account_id": validation.get("account_id"),
                "ec2_accessible": bool(ec2_ok),
                "message": "AWS connectivity verified" if ec2_ok else "AWS connectivity issues detected"
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "region": self.region,
                "environment": self.environment,
                "error": f"Health check failed: {str(e)}"
            }