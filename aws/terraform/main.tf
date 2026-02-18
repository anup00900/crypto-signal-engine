# ============================================================
# CRYPTO DATA COLLECTOR - AWS INFRASTRUCTURE
# ============================================================
# 
# This Terraform configuration creates:
# - S3 bucket for data storage
# - Lambda function for data collection
# - EventBridge rule for 15-minute scheduling
# - IAM roles and policies
# - Secrets Manager for API credentials
# - CloudWatch log groups
# - SNS topic for alerts (optional)
#
# Usage:
#   cd aws/terraform
#   terraform init
#   terraform plan
#   terraform apply
#
# ============================================================

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ============================================================
# VARIABLES
# ============================================================

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "eu-north-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "crypto-collector"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "currencies" {
  description = "Currencies to collect data for"
  type        = list(string)
  default     = ["BTC", "ETH"]
}

variable "schedule_rate" {
  description = "Data collection schedule"
  type        = string
  default     = "rate(15 minutes)"
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 1024
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 900  # 15 minutes max
}

variable "alert_email" {
  description = "Email for alerts (optional)"
  type        = string
  default     = ""
}

# ============================================================
# PROVIDER
# ============================================================

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  name_prefix = "${var.project_name}-${var.environment}"
}

# ============================================================
# S3 BUCKET - DATA STORAGE
# ============================================================

resource "aws_s3_bucket" "data" {
  bucket = "${local.name_prefix}-data-${local.account_id}"
  
  tags = {
    Name = "${local.name_prefix}-data"
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  
  rule {
    id     = "archive-old-data"
    status = "Enabled"
    
    filter {
      prefix = ""  # Apply to all objects
    }
    
    # Move to IA after 30 days
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    
    # Move to Glacier after 90 days
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    
    # Delete after 2 years (optional - comment out to keep forever)
    # expiration {
    #   days = 730
    # }
  }
  
  rule {
    id     = "cleanup-old-versions"
    status = "Enabled"
    
    filter {
      prefix = ""  # Apply to all objects
    }
    
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ============================================================
# SECRETS MANAGER - API CREDENTIALS
# ============================================================

resource "aws_secretsmanager_secret" "deribit" {
  name                    = "${local.name_prefix}/deribit"
  description             = "Deribit API credentials"
  recovery_window_in_days = 7
}

# Note: You need to manually set the secret value after creation:
# aws secretsmanager put-secret-value \
#   --secret-id crypto-collector-prod/deribit \
#   --secret-string '{"DERIBIT_CLIENT_ID":"your-id","DERIBIT_CLIENT_SECRET":"your-secret"}'

# ============================================================
# IAM ROLE - LAMBDA EXECUTION
# ============================================================

resource "aws_iam_role" "lambda" {
  name = "${local.name_prefix}-lambda-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.name_prefix}-lambda-policy"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logs
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
      # S3 Access
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*"
        ]
      },
      # Secrets Manager
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.deribit.arn
      },
      # SNS (for alerts)
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

# ============================================================
# CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name_prefix}"
  retention_in_days = 30
}

# ============================================================
# SNS TOPIC - ALERTS
# ============================================================

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ============================================================
# LAMBDA FUNCTION
# ============================================================

# Note: The Lambda package needs to be created separately
# See deploy.sh for packaging instructions

resource "aws_lambda_function" "collector" {
  function_name = local.name_prefix
  role          = aws_iam_role.lambda.arn
  handler       = "aws.lambda_handler.lambda_handler"
  runtime       = "python3.11"  # Upgraded from 3.9 (deprecated Dec 2025)
  
  # Will be updated by deployment script
  filename         = "${path.module}/../package/lambda.zip"
  source_code_hash = fileexists("${path.module}/../package/lambda.zip") ? filebase64sha256("${path.module}/../package/lambda.zip") : null
  
  memory_size = var.lambda_memory
  timeout     = var.lambda_timeout
  
  # Use AWS official pandas layer for Python 3.11 (includes pandas + numpy + pyarrow)
  layers = [
    "arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python311:17"
  ]
  
  environment {
    variables = {
      S3_BUCKET       = aws_s3_bucket.data.id
      SECRETS_NAME    = aws_secretsmanager_secret.deribit.name
      CURRENCIES      = join(",", var.currencies)
      ALERT_SNS_TOPIC = aws_sns_topic.alerts.arn
      ENVIRONMENT     = var.environment
    }
  }
  
  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda
  ]
  
  tags = {
    Name = local.name_prefix
  }
}

# ============================================================
# EVENTBRIDGE - SCHEDULING
# ============================================================

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.name_prefix}-schedule"
  description         = "Trigger crypto data collection every 15 minutes"
  schedule_expression = var.schedule_rate
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "TriggerLambda"
  arn       = aws_lambda_function.collector.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# ============================================================
# CLOUDWATCH ALARMS
# ============================================================

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Lambda function errors"
  
  dimensions = {
    FunctionName = aws_lambda_function.collector.function_name
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name          = "${local.name_prefix}-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Maximum"
  threshold           = 840000  # 14 minutes (warn before timeout)
  alarm_description   = "Lambda duration approaching timeout"
  
  dimensions = {
    FunctionName = aws_lambda_function.collector.function_name
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ============================================================
# OUTPUTS
# ============================================================

output "s3_bucket_name" {
  description = "S3 bucket for data storage"
  value       = aws_s3_bucket.data.id
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.data.arn
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.collector.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.collector.arn
}

output "secrets_manager_name" {
  description = "Secrets Manager secret name"
  value       = aws_secretsmanager_secret.deribit.name
}

output "sns_topic_arn" {
  description = "SNS topic for alerts"
  value       = aws_sns_topic.alerts.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group"
  value       = aws_cloudwatch_log_group.lambda.name
}

output "schedule_rule" {
  description = "EventBridge schedule rule"
  value       = aws_cloudwatch_event_rule.schedule.name
}

output "next_steps" {
  description = "Next steps after deployment"
  value       = <<-EOT
    
    ============================================================
    DEPLOYMENT SUCCESSFUL! 
    ============================================================
    
    Next steps:
    
    1. Set your Deribit API credentials:
       aws secretsmanager put-secret-value \
         --secret-id ${aws_secretsmanager_secret.deribit.name} \
         --secret-string '{"DERIBIT_CLIENT_ID":"your-id","DERIBIT_CLIENT_SECRET":"your-secret"}'
    
    2. Test the Lambda function:
       aws lambda invoke \
         --function-name ${aws_lambda_function.collector.function_name} \
         --payload '{}' \
         response.json
    
    3. Check the logs:
       aws logs tail ${aws_cloudwatch_log_group.lambda.name} --follow
    
    4. View collected data:
       aws s3 ls s3://${aws_s3_bucket.data.id}/latest/
    
    ============================================================
  EOT
}

