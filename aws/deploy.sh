#!/bin/bash
# ============================================================
# CRYPTO DATA COLLECTOR - AWS DEPLOYMENT SCRIPT
# ============================================================
#
# This script:
# 1. Creates the Lambda deployment package
# 2. Deploys infrastructure with Terraform
# 3. Sets up your Deribit API credentials
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# ============================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo -e "${BLUE}"
echo "============================================================"
echo "    CRYPTO DATA COLLECTOR - AWS DEPLOYMENT"
echo "============================================================"
echo -e "${NC}"

# ============================================================
# STEP 1: CHECK PREREQUISITES
# ============================================================

echo -e "${YELLOW}Step 1: Checking prerequisites...${NC}"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    echo "Install it from: https://aws.amazon.com/cli/"
    exit 1
fi

# Check Terraform
if ! command -v terraform &> /dev/null; then
    echo -e "${RED}Error: Terraform is not installed${NC}"
    echo "Install it from: https://terraform.io/downloads"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
fi

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region || echo "eu-north-1")

echo -e "${GREEN}✓ AWS CLI configured (Account: $AWS_ACCOUNT, Region: $AWS_REGION)${NC}"
echo -e "${GREEN}✓ Terraform installed${NC}"
echo -e "${GREEN}✓ Python 3 installed${NC}"

# ============================================================
# STEP 2: CREATE LAMBDA DEPLOYMENT PACKAGE
# ============================================================

echo ""
echo -e "${YELLOW}Step 2: Creating Lambda deployment package...${NC}"

PACKAGE_DIR="$SCRIPT_DIR/package"
mkdir -p "$PACKAGE_DIR"

# Create a temporary directory for building
BUILD_DIR=$(mktemp -d)
echo "Building in: $BUILD_DIR"

# Install dependencies (pandas/numpy from Lambda Layer, no pydantic needed)
echo "Installing lightweight dependencies..."
pip3 install --target "$BUILD_DIR" --upgrade \
    aiohttp websockets loguru boto3 flask mangum asgiref 2>/dev/null || \
pip3 install --target "$BUILD_DIR" --upgrade \
    aiohttp websockets loguru boto3 flask mangum asgiref

# Copy ONLY the files we need (avoid importing pydantic via __init__.py)
echo "Copying project code..."

# AWS module
mkdir -p "$BUILD_DIR/aws"
cp "$SCRIPT_DIR"/*.py "$BUILD_DIR/aws/"

# Signal Lambda module
cp -r "$SCRIPT_DIR/signal_lambda" "$BUILD_DIR/aws/signal_lambda"

# Dashboard Lambda module
cp -r "$SCRIPT_DIR/dashboard_lambda" "$BUILD_DIR/aws/dashboard_lambda"

# Web module (Flask dashboard app)
cp -r "$PROJECT_ROOT/web" "$BUILD_DIR/web"
touch "$BUILD_DIR/web/__init__.py"

# Only copy the api_client we actually use (not the whole collectors tree)
mkdir -p "$BUILD_DIR/collectors/deribit"
echo '"""Collectors"""' > "$BUILD_DIR/collectors/__init__.py"
echo '"""Deribit"""' > "$BUILD_DIR/collectors/deribit/__init__.py"
cp "$PROJECT_ROOT/collectors/deribit/api_client.py" "$BUILD_DIR/collectors/deribit/"

# Utils (minimal)
mkdir -p "$BUILD_DIR/utils"
echo '"""Utils"""' > "$BUILD_DIR/utils/__init__.py"

# Config (empty - not needed)
mkdir -p "$BUILD_DIR/config"
echo '"""Config"""' > "$BUILD_DIR/config/__init__.py"

# Create __init__.py files
touch "$BUILD_DIR/__init__.py"
touch "$BUILD_DIR/aws/__init__.py"

# Create the zip file
echo "Creating zip package..."
cd "$BUILD_DIR"
zip -r9 "$PACKAGE_DIR/lambda.zip" . -x "*.pyc" -x "__pycache__/*" -x "*.dist-info/*"

# Cleanup
rm -rf "$BUILD_DIR"

PACKAGE_SIZE=$(du -h "$PACKAGE_DIR/lambda.zip" | cut -f1)
echo -e "${GREEN}✓ Lambda package created: $PACKAGE_DIR/lambda.zip ($PACKAGE_SIZE)${NC}"

# ============================================================
# STEP 3: DEPLOY TERRAFORM INFRASTRUCTURE
# ============================================================

echo ""
echo -e "${YELLOW}Step 3: Deploying AWS infrastructure with Terraform...${NC}"

cd "$SCRIPT_DIR/terraform"

# Initialize Terraform
echo "Initializing Terraform..."
terraform init

# Plan
echo "Planning deployment..."
terraform plan -out=tfplan

# Ask for confirmation
echo ""
echo -e "${YELLOW}Review the plan above. Do you want to apply? (yes/no)${NC}"
read -r CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 1
fi

# Apply
echo "Applying Terraform configuration..."
terraform apply tfplan

# Get outputs
S3_BUCKET=$(terraform output -raw s3_bucket_name)
LAMBDA_NAME=$(terraform output -raw lambda_function_name)
SECRET_NAME=$(terraform output -raw secrets_manager_name)

echo -e "${GREEN}✓ Infrastructure deployed successfully${NC}"

# ============================================================
# STEP 4: SET UP API CREDENTIALS
# ============================================================

echo ""
echo -e "${YELLOW}Step 4: Setting up Deribit API credentials...${NC}"

echo "Do you have Deribit API credentials? (yes/no)"
read -r HAS_CREDS

if [ "$HAS_CREDS" == "yes" ]; then
    echo "Enter your Deribit Client ID:"
    read -r DERIBIT_CLIENT_ID
    
    echo "Enter your Deribit Client Secret:"
    read -rs DERIBIT_CLIENT_SECRET
    echo ""
    
    # Store in Secrets Manager
    aws secretsmanager put-secret-value \
        --secret-id "$SECRET_NAME" \
        --secret-string "{\"DERIBIT_CLIENT_ID\":\"$DERIBIT_CLIENT_ID\",\"DERIBIT_CLIENT_SECRET\":\"$DERIBIT_CLIENT_SECRET\"}"
    
    echo -e "${GREEN}✓ Credentials stored in Secrets Manager${NC}"
else
    echo -e "${YELLOW}You can set credentials later with:${NC}"
    echo "aws secretsmanager put-secret-value \\"
    echo "  --secret-id $SECRET_NAME \\"
    echo "  --secret-string '{\"DERIBIT_CLIENT_ID\":\"your-id\",\"DERIBIT_CLIENT_SECRET\":\"your-secret\"}'"
fi

# ============================================================
# STEP 5: TEST THE DEPLOYMENT
# ============================================================

echo ""
echo -e "${YELLOW}Step 5: Testing the deployment...${NC}"

echo "Do you want to run a test now? (yes/no)"
read -r RUN_TEST

if [ "$RUN_TEST" == "yes" ]; then
    echo "Invoking Lambda function..."
    
    aws lambda invoke \
        --function-name "$LAMBDA_NAME" \
        --payload '{"test": true}' \
        --cli-binary-format raw-in-base64-out \
        /tmp/lambda-response.json
    
    echo "Response:"
    cat /tmp/lambda-response.json
    echo ""
    
    # Check logs
    echo ""
    echo "Recent logs:"
    sleep 5  # Wait for logs to appear
    aws logs tail "/aws/lambda/$LAMBDA_NAME" --since 5m --format short || true
fi

# ============================================================
# SUMMARY
# ============================================================

echo ""
echo -e "${GREEN}"
echo "============================================================"
echo "    DEPLOYMENT COMPLETE! 🎉"
echo "============================================================"
echo -e "${NC}"

echo "Resources created:"
echo "  • S3 Bucket:    $S3_BUCKET"
echo "  • Lambda:       $LAMBDA_NAME"
echo "  • Schedule:     Every 15 minutes"
echo ""

echo "Useful commands:"
echo ""
echo "  # View latest data"
echo "  aws s3 ls s3://$S3_BUCKET/latest/"
echo ""
echo "  # Download latest options data"
echo "  aws s3 cp s3://$S3_BUCKET/latest/options_surface_BTC.csv ."
echo ""
echo "  # View Lambda logs"
echo "  aws logs tail /aws/lambda/$LAMBDA_NAME --follow"
echo ""
echo "  # Manually trigger collection"
echo "  aws lambda invoke --function-name $LAMBDA_NAME response.json"
echo ""
echo "  # Check S3 data size"
echo "  aws s3 ls s3://$S3_BUCKET --recursive --summarize | tail -2"
echo ""

echo -e "${BLUE}Your pipeline is now running automatically every 15 minutes!${NC}"

