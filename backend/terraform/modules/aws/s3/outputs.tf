output "bucket_name" {
  description = "S3 bucket name"
  value       = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.this.arn
}

output "bucket_domain_name" {
  description = "S3 bucket domain name"
  value       = aws_s3_bucket.this.bucket_domain_name
}

output "bucket_region" {
  description = "S3 bucket region"
  value       = aws_s3_bucket.this.region
}

output "console_url" {
  description = "AWS console URL to view this S3 bucket"
  value       = "https://console.aws.amazon.com/s3/buckets/${aws_s3_bucket.this.bucket}?region=${var.aws_region}"
}

output "region" {
  description = "AWS region"
  value       = var.aws_region
}