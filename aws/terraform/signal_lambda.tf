# ============================================================
# SIGNAL ENGINE LAMBDA - 1-MINUTE BINANCE SIGNALS
# ============================================================
#
# Separate Lambda that runs every 1 minute via EventBridge.
# Fetches Binance Futures REST data, computes 7 trading signals,
# writes results to S3. Shares the same S3 bucket and IAM role
# as the existing Deribit collector Lambda.
#
# ============================================================

# ============================================================
# CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "signal_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-signal-engine"
  retention_in_days = 7
}

# ============================================================
# LAMBDA FUNCTION
# ============================================================

resource "aws_lambda_function" "signal_engine" {
  function_name = "${local.name_prefix}-signal-engine"
  role          = aws_iam_role.lambda.arn
  handler       = "aws.signal_lambda.handler.lambda_handler"
  runtime       = "python3.11"

  # Same deployment package as the collector Lambda
  filename         = "${path.module}/../package/lambda.zip"
  source_code_hash = fileexists("${path.module}/../package/lambda.zip") ? filebase64sha256("${path.module}/../package/lambda.zip") : null

  memory_size = 256
  timeout     = 30

  # AWS SDK Pandas layer (includes pandas + numpy + pyarrow)
  layers = [
    "arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python311:17"
  ]

  environment {
    variables = {
      S3_BUCKET   = aws_s3_bucket.data.id
      ENVIRONMENT = var.environment
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.signal_lambda,
    aws_iam_role_policy.lambda
  ]

  tags = {
    Name = "${local.name_prefix}-signal-engine"
  }
}

# ============================================================
# EVENTBRIDGE - 1 MINUTE SCHEDULE
# ============================================================

resource "aws_cloudwatch_event_rule" "signal_schedule" {
  name                = "${local.name_prefix}-signal-engine-schedule"
  description         = "Trigger signal engine every 1 minute"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "signal_lambda" {
  rule      = aws_cloudwatch_event_rule.signal_schedule.name
  target_id = "TriggerSignalLambda"
  arn       = aws_lambda_function.signal_engine.arn
}

resource "aws_lambda_permission" "signal_eventbridge" {
  statement_id  = "AllowEventBridgeInvokeSignal"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.signal_engine.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.signal_schedule.arn
}

# ============================================================
# CLOUDWATCH ALARM - SIGNAL ENGINE ERRORS
# ============================================================

resource "aws_cloudwatch_metric_alarm" "signal_lambda_errors" {
  alarm_name          = "${local.name_prefix}-signal-engine-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "Signal engine Lambda errors (>3 in 5 min)"

  dimensions = {
    FunctionName = aws_lambda_function.signal_engine.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# ============================================================
# OUTPUTS
# ============================================================

output "signal_lambda_function_name" {
  description = "Signal engine Lambda function name"
  value       = aws_lambda_function.signal_engine.function_name
}

output "signal_lambda_function_arn" {
  description = "Signal engine Lambda function ARN"
  value       = aws_lambda_function.signal_engine.arn
}

output "signal_schedule_rule" {
  description = "Signal engine EventBridge schedule rule"
  value       = aws_cloudwatch_event_rule.signal_schedule.name
}

output "signal_cloudwatch_log_group" {
  description = "Signal engine CloudWatch log group"
  value       = aws_cloudwatch_log_group.signal_lambda.name
}
