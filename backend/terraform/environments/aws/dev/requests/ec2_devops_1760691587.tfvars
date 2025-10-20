# AMI Filter: ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*
# Operating System: Ubuntu 22.04 LTS (Latest)
# Terraform will find LATEST AMI using the filter above
request_id = "ec2_devops_1760691587"
department = "devops"
created_by = "user@company.com"
environment = "qa"
instance_type = "t3.small"
storage_size = 30
region = "us-west-2"
operating_system = "ubuntu"
ami_filter = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
ami_owners = ["099720109477"]
associate_public_ip = true
key_name = "prod-keypair"
create_new_keypair = false
vpc_id = ""
use_existing_vpc = false
subnet_id = ""
use_existing_subnet = false
security_group_id = ""
use_existing_sg = false
instance_tags = {
  "Name" = "user-ec2-1760691587"
  "Department" = "devops"
  "Environment" = "qa"
  "RequestID" = "ec2_devops_1760691587"
  "CreatedBy" = "user@company.com"
  "ManagedBy" = "AIOps-Platform"
  "OS" = "ubuntu"
}