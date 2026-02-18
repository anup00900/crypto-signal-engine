# ============================================================
# CRYPTO DATA COLLECTOR - TERRAFORM VARIABLES
# ============================================================
# 
# Customize these values for your deployment
#
# ============================================================

# AWS Region - Stockholm (your current region)
aws_region = "eu-north-1"

# Project naming
project_name = "crypto-collector"
environment  = "prod"

# Currencies to collect
currencies = ["BTC", "ETH"]

# Collection schedule (every 15 minutes)
schedule_rate = "rate(15 minutes)"

# Lambda configuration
lambda_memory  = 1024  # MB
lambda_timeout = 900   # seconds (15 min max)

# Alert email (optional - leave empty to disable)
# alert_email = "your-email@example.com"
alert_email = ""

