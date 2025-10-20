request_id = "devops_aws_dev_eb6791b7"
department = "DevOps"
created_by = "manoharkadimisetti3@gmail.com"
environment = "dev"
instance_type = "t3.micro"
storage_size = 8
region = "us-east-1"
associate_public_ip = true
storage_type = "gp3"
subnet_type = "public"
ami_filter = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
ami_owners = ["099720109477"]
ami_id = ""
key_name = "auto-engineering-45d5b8"
keypair_name = "auto-engineering-45d5b8"
create_new_keypair = false
vpc_id = ""
use_existing_vpc = false
subnet_id = ""
use_existing_subnet = false
security_group_id = ""
use_existing_sg = false
security_group_rules = [
  {
    port        = 22
    protocol    = "tcp"
    cidr        = "0.0.0.0/0"
    description = "SSH access"
  },
  {
    port        = 80
    protocol    = "tcp"
    cidr        = "0.0.0.0/0"
    description = "HTTP access"
  },
  {
    port        = 443
    protocol    = "tcp"
    cidr        = "0.0.0.0/0"
    description = "HTTPS access"
  }
]
user_data = ""
user_data_base64 = ""
instance_tags = {
  "Name" = "manohar-ec2-eb6791b7"
  "Department" = "DevOps"
  "Environment" = "dev"
  "RequestID" = "devops_aws_dev_eb6791b7"
  "CreatedBy" = "manoharkadimisetti3@gmail.com"
  "ManagedBy" = "AIOps-Platform"
}
