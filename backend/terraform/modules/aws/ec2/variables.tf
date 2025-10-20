variable "operating_system" {
  type        = string
  description = "Operating system type from user input"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type from user input"
}

variable "storage_size" {
  type        = number
  description = "Storage size in GB from user input"
}

variable "region" {
  type        = string
  description = "AWS region from user input"
}

variable "ami_filter" {
  type        = string
  description = "Dynamic AMI filter from MCP service"
}

variable "ami_owners" {
  type        = list(string)
  description = "AMI owners from MCP service"
}

variable "ami_id" {
  type        = string
  description = "Specific AMI ID from MCP service (overrides filter)"
  default     = ""
}

variable "key_name" {
  type        = string
  description = "SSH key pair name"
}

variable "create_new_keypair" {
  type        = bool
  description = "Whether to create new keypair"
  default     = false
}

variable "use_existing_vpc" {
  type        = bool
  description = "Use existing VPC"
  default     = false
}

variable "vpc_id" {
  type        = string
  description = "Existing VPC ID"
  default     = ""
}

variable "use_existing_subnet" {
  type        = bool
  description = "Use existing subnet"
  default     = false
}

variable "subnet_id" {
  type        = string
  description = "Existing subnet ID"
  default     = ""
}

variable "use_existing_sg" {
  type        = bool
  description = "Use existing security group"
  default     = false
}

variable "security_group_id" {
  type        = string
  description = "Existing security group ID"
  default     = ""
}

variable "associate_public_ip" {
  type        = bool
  description = "Associate public IP"
  default     = true
}

variable "instance_tags" {
  type        = map(string)
  description = "Instance tags"
  default     = {}
}