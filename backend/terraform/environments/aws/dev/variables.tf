# Common variables
variable "region" {
  type        = string
  description = "AWS region"
  default     = "us-east-1"
}

# EC2 Variables
variable "operating_system" {
  type        = string
  description = "Operating system type"
  default     = null
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type"
  default     = null
}

variable "storage_size" {
  type        = number
  description = "Storage size in GB"
  default     = null
}

variable "ami_filter" {
  type        = string
  description = "AMI filter pattern"
  default     = null
}

variable "ami_owners" {
  type        = list(string)
  description = "AMI owners"
  default     = null
}

variable "key_name" {
  type        = string
  description = "SSH key pair name"
  default     = null
}

variable "create_new_keypair" {
  type        = bool
  description = "Create new keypair"
  default     = false
}

variable "associate_public_ip" {
  type        = bool
  description = "Associate public IP"
  default     = true
}

variable "use_existing_vpc" {
  type        = bool
  description = "Use existing VPC"
  default     = false
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
  default     = ""
}

variable "use_existing_subnet" {
  type        = bool
  description = "Use existing subnet"
  default     = false
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID"
  default     = ""
}

variable "use_existing_sg" {
  type        = bool
  description = "Use existing security group"
  default     = false
}

variable "security_group_id" {
  type        = string
  description = "Security group ID"
  default     = ""
}

variable "instance_tags" {
  type        = map(string)
  description = "Instance tags"
  default     = {}
}

# S3 Variables
variable "bucket_name" {
  type        = string
  description = "S3 bucket name"
  default     = null
}

variable "aws_region" {
  type        = string
  description = "AWS region for S3/Lambda"
  default     = null
}

variable "versioning_enabled" {
  type        = bool
  description = "Enable S3 versioning"
  default     = false
}

variable "block_public_access" {
  type        = bool
  description = "Block S3 public access"
  default     = true
}

# Lambda Variables
variable "lambda_function_name" {
  type        = string
  description = "Lambda function name"
  default     = null
}

variable "lambda_runtime" {
  type        = string
  description = "Lambda runtime"
  default     = null
}

variable "lambda_handler" {
  type        = string
  description = "Lambda handler"
  default     = null
}

variable "lambda_timeout" {
  type        = number
  description = "Lambda timeout in seconds"
  default     = null
}

variable "lambda_memory_size" {
  type        = number
  description = "Lambda memory size in MB"
  default     = null
}