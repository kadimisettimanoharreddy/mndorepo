output "instance_id" {
  description = "EC2 instance id"
  value       = aws_instance.main.id
}

output "instance_name" {
  description = "EC2 instance name tag"
  value       = aws_instance.main.tags["Name"]
}

output "public_ip" {
  description = "Public IP of the instance (if one was assigned)"
  value       = aws_instance.main.public_ip
  sensitive   = false
}

output "private_ip" {
  description = "Private IP of the instance"
  value       = aws_instance.main.private_ip
  sensitive   = false
}

output "public_dns" {
  description = "Public DNS (if any)"
  value       = aws_instance.main.public_dns
}

output "availability_zone" {
  description = "Availability zone of the instance"
  value       = aws_instance.main.availability_zone
}

output "security_group_id" {
  description = "Security group used for the instance"
  value       = var.use_existing_sg ? var.security_group_id : aws_security_group.default[0].id
}

output "key_name" {
  description = "Key pair name attached to the instance"
  value       = aws_instance.main.key_name
}

output "console_url" {
  description = "AWS console URL to view this instance"
  value       = "https://console.aws.amazon.com/ec2/v2/home?region=${data.aws_region.current.name}#InstanceDetails:instanceId=${aws_instance.main.id}"
}

output "private_key_ssm_parameter" {
  description = "SSM parameter name where private key is stored (if created)"
  value       = var.create_new_keypair ? aws_ssm_parameter.private_key[0].name : null
}

output "ip_type" {
  description = "IP type (Public or Private)"
  value       = aws_instance.main.public_ip != null ? "Public" : "Private"
}
