# Enhanced EC2 Request Example - All Features Demonstrated
# This file shows all possible parameters that can be generated dynamically

# Basic Request Information
request_id = "devops_aws_dev_12345678"
department = "DevOps"
created_by = "user@company.com"
environment = "dev"
region = "us-east-1"

# Instance Configuration
instance_type = "t3.small"
ami_id = "ami-ubuntu2004"  # Specific AMI ID (overrides ami_filter)
# OR use ami_filter for dynamic AMI selection
ami_filter = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
ami_owners = ["099720109477"]

# Storage Configuration
storage_size = 30
storage_type = "gp3"
iops = 3000          # Only for io1/io2 volumes
throughput = 125     # Only for gp3 volumes

# Networking Configuration
vpc_id = "vpc-finance"
use_existing_vpc = true
subnet_id = "subnet-priv-123"
use_existing_subnet = true
subnet_type = "private"
associate_public_ip = false

# Security Group Configuration
security_group_id = "sg-custom-123"
use_existing_sg = true
# OR use custom security group rules for new SG
security_group_rules = [
  {
    port = 22
    protocol = "tcp"
    cidr = "10.0.0.0/16"
    description = "SSH access from VPC"
  },
  {
    port = 3306
    protocol = "tcp"
    cidr = "10.0.0.0/16"
    description = "MySQL database access"
  },
  {
    port = 80
    protocol = "tcp"
    cidr = "0.0.0.0/0"
    description = "HTTP web access"
  }
]

# Keypair Configuration
key_name = "my-dev-key"
keypair_name = "my-dev-key"  # Alternative field name
create_new_keypair = false

# Advanced Instance Settings
availability_zone = "us-east-1a"
enable_monitoring = true
disable_api_termination = false
ebs_optimized = true

# User Data for Software Installation
user_data = "#!/bin/bash\napt update && apt install -y mysql-server nginx\nsystemctl enable mysql nginx\nsystemctl start mysql nginx"

# Alternative: Base64 encoded user data
user_data_base64 = ""

# Instance Tags
instance_tags = {
  "Name" = "user-ec2-12345678"
  "Department" = "DevOps"
  "Environment" = "dev"
  "RequestID" = "devops_aws_dev_12345678"
  "CreatedBy" = "user@company.com"
  "ManagedBy" = "AIOps-Platform"
  "Project" = "Database-Server"
  "CostCenter" = "Engineering"
}