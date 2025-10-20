request_id = "7c121778"
department = "engineering"
created_by = "manohar"
environment = "dev"
region = "us-east-1"

# Instance Configuration
instance_type = "t3.micro"
storage_size = 8

# Ubuntu 20.04 LTS AMI
ami_filter = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
ami_owners = ["099720109477"]

# Networking - Using defaults (default VPC, public subnet)
use_existing_vpc = false
use_existing_subnet = false
use_existing_sg = false
associate_public_ip = true

# Key Pair - Create new one
key_name = "manohar-dev-key-7c121778"
create_new_keypair = true

# Instance Tags
instance_tags = {
  Name = "manohar-dev-instance-7c121778"
  Environment = "dev"
  Owner = "manohar"
  Purpose = "development"
  RequestId = "7c121778"
  CreatedBy = "AIOps-Platform"
}