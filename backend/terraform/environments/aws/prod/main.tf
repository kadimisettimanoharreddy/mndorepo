terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.1"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Environment = "dev"
      Project     = "aiops-platform"
      ManagedBy   = "terraform"
    }
  }
}

# Determine service type from tfvars
locals {
  is_ec2    = can(var.operating_system) && can(var.instance_type)
  is_s3     = can(var.bucket_name) && can(var.aws_region)
  is_lambda = can(var.lambda_function_name) && can(var.lambda_runtime)
}

# EC2 Instance Module
module "ec2_instance" {
  count  = local.is_ec2 ? 1 : 0
  source = "../../../modules/aws/ec2"

  operating_system    = var.operating_system
  instance_type       = var.instance_type
  storage_size        = var.storage_size
  region              = var.region
  ami_filter          = var.ami_filter
  ami_owners          = var.ami_owners
  key_name            = var.key_name
  create_new_keypair  = var.create_new_keypair
  associate_public_ip = var.associate_public_ip
  use_existing_vpc    = var.use_existing_vpc
  vpc_id              = var.vpc_id
  use_existing_subnet = var.use_existing_subnet
  subnet_id           = var.subnet_id
  use_existing_sg     = var.use_existing_sg
  security_group_id   = var.security_group_id
  instance_tags       = var.instance_tags
}

# S3 Bucket Module
module "s3_bucket" {
  count  = local.is_s3 ? 1 : 0
  source = "../../../modules/aws/s3"

  bucket_name         = var.bucket_name
  aws_region          = var.aws_region
  versioning_enabled  = var.versioning_enabled
  block_public_access = var.block_public_access
}

# Lambda Function Module
module "lambda_function" {
  count  = local.is_lambda ? 1 : 0
  source = "../../../modules/aws/lambda"

  lambda_function_name = var.lambda_function_name
  lambda_runtime       = var.lambda_runtime
  lambda_handler       = var.lambda_handler
  lambda_timeout       = var.lambda_timeout
  lambda_memory_size   = var.lambda_memory_size
  aws_region           = var.aws_region
}