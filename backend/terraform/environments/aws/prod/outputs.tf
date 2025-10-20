# EC2 Outputs
output "instance_id" {
  description = "EC2 instance ID"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].instance_id : null
}

output "instance_name" {
  description = "EC2 instance name"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].instance_name : null
}

output "public_ip" {
  description = "EC2 public IP"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].public_ip : null
}

output "private_ip" {
  description = "EC2 private IP"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].private_ip : null
}

output "ip_type" {
  description = "IP type (Public or Private)"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].ip_type : null
}

output "availability_zone" {
  description = "EC2 availability zone"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].availability_zone : null
}

output "console_url" {
  description = "AWS console URL"
  value       = length(module.ec2_instance) > 0 ? module.ec2_instance[0].console_url : (
    length(module.s3_bucket) > 0 ? module.s3_bucket[0].console_url : (
      length(module.lambda_function) > 0 ? module.lambda_function[0].console_url : null
    )
  )
}

# S3 Outputs
output "bucket_name" {
  description = "S3 bucket name"
  value       = length(module.s3_bucket) > 0 ? module.s3_bucket[0].bucket_name : null
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = length(module.s3_bucket) > 0 ? module.s3_bucket[0].bucket_arn : null
}

output "bucket_domain_name" {
  description = "S3 bucket domain name"
  value       = length(module.s3_bucket) > 0 ? module.s3_bucket[0].bucket_domain_name : null
}

output "bucket_region" {
  description = "S3 bucket region"
  value       = length(module.s3_bucket) > 0 ? module.s3_bucket[0].bucket_region : null
}

# Lambda Outputs
output "function_name" {
  description = "Lambda function name"
  value       = length(module.lambda_function) > 0 ? module.lambda_function[0].function_name : null
}

output "function_arn" {
  description = "Lambda function ARN"
  value       = length(module.lambda_function) > 0 ? module.lambda_function[0].function_arn : null
}

output "function_url" {
  description = "Lambda function URL"
  value       = length(module.lambda_function) > 0 ? module.lambda_function[0].function_url : null
}

output "runtime" {
  description = "Lambda runtime"
  value       = length(module.lambda_function) > 0 ? module.lambda_function[0].runtime : null
}

# Common Outputs
output "region" {
  description = "AWS region"
  value       = length(module.ec2_instance) > 0 ? var.region : (
    length(module.s3_bucket) > 0 ? module.s3_bucket[0].region : (
      length(module.lambda_function) > 0 ? module.lambda_function[0].region : var.region
    )
  )
}