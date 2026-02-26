# ============================================================
# DASHBOARD LAMBDA - FLASK WEB UI VIA API GATEWAY HTTP API
# ============================================================
#
# Hosts the Flask dashboard (web/dashboard.py) as a serverless
# Lambda behind an API Gateway HTTP API (v2) for public access.
#
# ============================================================

# ============================================================
# CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "dashboard_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-dashboard"
  retention_in_days = 7
}

# ============================================================
# LAMBDA FUNCTION
# ============================================================

resource "aws_lambda_function" "dashboard" {
  function_name = "${local.name_prefix}-dashboard"
  role          = aws_iam_role.lambda.arn
  handler       = "aws.dashboard_lambda.handler.lambda_handler"
  runtime       = "python3.11"

  # Same deployment package as the other Lambdas
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
    aws_cloudwatch_log_group.dashboard_lambda,
    aws_iam_role_policy.lambda
  ]

  tags = {
    Name = "${local.name_prefix}-dashboard"
  }
}

# ============================================================
# API GATEWAY HTTP API (v2) — PUBLIC ENDPOINT
# ============================================================

resource "aws_apigatewayv2_api" "dashboard" {
  name          = "${local.name_prefix}-dashboard"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "dashboard" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.dashboard.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "dashboard_default" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard.id}"
}

resource "aws_apigatewayv2_stage" "dashboard" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "dashboard_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dashboard.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/*"
}

# ============================================================
# OUTPUTS
# ============================================================

output "dashboard_url" {
  description = "Public URL for the dashboard"
  value       = aws_apigatewayv2_stage.dashboard.invoke_url
}

output "dashboard_lambda_function_name" {
  description = "Dashboard Lambda function name"
  value       = aws_lambda_function.dashboard.function_name
}
