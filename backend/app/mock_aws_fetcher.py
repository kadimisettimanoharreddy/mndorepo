"""Mock AWS fetcher for testing networking flow without real AWS calls"""

class MockAWSResourceFetcher:
    def __init__(self, environment: str, region: str):
        self.environment = environment
        self.region = region
    
    async def get_vpcs(self):
        return [
            {"id": "vpc-12345678", "cidr": "10.0.0.0/16", "state": "available"},
            {"id": "vpc-87654321", "cidr": "172.16.0.0/16", "state": "available"}
        ]
    
    async def get_vpc_details(self, vpc_id: str):
        vpcs = {
            "vpc-12345678": {"id": "vpc-12345678", "cidr": "10.0.0.0/16", "state": "available"},
            "vpc-87654321": {"id": "vpc-87654321", "cidr": "172.16.0.0/16", "state": "available"}
        }
        return vpcs.get(vpc_id)
    
    async def get_subnets(self, vpc_id: str):
        return [
            {"id": "subnet-11111111", "cidr": "10.0.1.0/24", "public": True, "availability_zone": "us-east-1a", "vpc_id": vpc_id},
            {"id": "subnet-22222222", "cidr": "10.0.2.0/24", "public": False, "availability_zone": "us-east-1b", "vpc_id": vpc_id}
        ]
    
    async def get_subnet_details(self, subnet_id: str):
        subnets = {
            "subnet-11111111": {"id": "subnet-11111111", "cidr": "10.0.1.0/24", "public": True, "availability_zone": "us-east-1a", "vpc_id": "vpc-12345678"},
            "subnet-22222222": {"id": "subnet-22222222", "cidr": "10.0.2.0/24", "public": False, "availability_zone": "us-east-1b", "vpc_id": "vpc-12345678"}
        }
        return subnets.get(subnet_id)
    
    async def get_security_groups(self, vpc_id: str):
        return [
            {"id": "sg-default", "name": "default", "description": "Default security group"},
            {"id": "sg-11111111", "name": "web-sg", "description": "Web server security group"}
        ]
    
    async def get_security_group_details(self, sg_id: str):
        sgs = {
            "sg-default": {"id": "sg-default", "name": "default", "description": "Default security group", "vpc_id": "vpc-12345678"},
            "sg-11111111": {"id": "sg-11111111", "name": "web-sg", "description": "Web server security group", "vpc_id": "vpc-12345678"}
        }
        return sgs.get(sg_id)
    
    async def get_security_group_rules(self, sg_id: str):
        return {
            "ingress": [
                {"port": "22", "protocol": "tcp", "source": "0.0.0.0/0"},
                {"port": "80", "protocol": "tcp", "source": "0.0.0.0/0"},
                {"port": "443", "protocol": "tcp", "source": "0.0.0.0/0"}
            ],
            "egress": [
                {"port": None, "protocol": "-1", "destination": "0.0.0.0/0"}
            ]
        }
    
    async def get_keypairs(self):
        return [
            {"name": "auto-engineering-0fa1db"},
            {"name": "my-keypair"},
            {"name": "dev-keypair"}
        ]
    
    async def check_keypair_exists(self, keypair_name: str):
        existing_keypairs = ["auto-engineering-0fa1db", "my-keypair", "dev-keypair"]
        return keypair_name in existing_keypairs