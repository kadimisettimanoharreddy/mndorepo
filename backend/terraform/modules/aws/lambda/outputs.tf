output "function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.this.arn
}

output "invoke_arn" {
  description = "Lambda function invoke ARN"
  value       = aws_lambda_function.this.invoke_arn
}

output "function_url" {
  description = "Lambda function URL"
  value       = aws_lambda_function.this.qualified_arn
}

output "runtime" {
  description = "Lambda runtime"
  value       = aws_lambda_function.this.runtime
}

output "console_url" {
  description = "AWS console URL to view this Lambda function"
  value       = "https://console.aws.amazon.com/lambda/home?region=${var.aws_region}#/functions/${aws_lambda_function.this.function_name}"
}

output "region" {
  description = "AWS region"
  value       = var.aws_region
}