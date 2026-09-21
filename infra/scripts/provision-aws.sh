#!/bin/bash
# Reference provisioning script — creates every AWS resource this project
# needs: a key pair, two security groups (app tier / inference tier), the
# app instance with an Elastic IP, and the GPU inference instance as a
# persistent spot request.
#
# Run this from your own machine with the AWS CLI installed and configured
# (`aws configure`), NOT from inside this session — it needs credentials
# this assistant does not have. Read it before running it; it is meant to
# be copy-pasted section by section on a first deploy, not blindly executed
# end to end. See docs/DEPLOY.md for the full walkthrough this belongs to.
#
# Prerequisites (see docs/DEPLOY.md Phase 0):
#   - AWS account with a payment method attached
#   - Billing alarm set (infra/scripts/billing-alarm.sh)
#   - GPU quota increase requested (infra/scripts/request-gpu-quota.sh) —
#     this script's GPU step will fail with an InsufficientInstanceCapacity
#     or VcpuLimitExceeded error until that's approved. That's expected;
#     re-run just the GPU section once it lands, or use
#     cpu-instance-userdata.sh as the contingency in the meantime.

set -euo pipefail

# ============================== CONFIG ==================================
AWS_REGION="us-east-1"                      # pick a region with good g4dn spot capacity
KEY_NAME="vlm-card-key"
APP_INSTANCE_TYPE="t3.micro"                # free-tier eligible
GPU_INSTANCE_TYPE="g4dn.xlarge"
REPO_URL="https://github.com/CHANGE-ME/vlm-business-card.git"  # your pushed repo
MY_IP_CIDR="$(curl -s https://checkip.amazonaws.com)/32"       # SSH access restricted to you
# ==========================================================================

export AWS_DEFAULT_REGION="$AWS_REGION"

echo "==> Using region: $AWS_REGION"
echo "==> SSH will be restricted to: $MY_IP_CIDR"

# --- 1. Key pair --------------------------------------------------------
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" &>/dev/null; then
    aws ec2 create-key-pair --key-name "$KEY_NAME" \
        --query 'KeyMaterial' --output text > "${KEY_NAME}.pem"
    chmod 400 "${KEY_NAME}.pem"
    echo "==> Wrote ${KEY_NAME}.pem — keep this safe, it is not recoverable if lost."
else
    echo "==> Key pair $KEY_NAME already exists, skipping."
fi

# --- 2. Default VPC ------------------------------------------------------
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text)
echo "==> Using default VPC: $VPC_ID"

# --- 3. Security groups ---------------------------------------------------
APP_SG_ID=$(aws ec2 create-security-group \
    --group-name vlm-app-sg \
    --description "App tier: HTTP/HTTPS public, SSH from admin IP only" \
    --vpc-id "$VPC_ID" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" \
    --protocol tcp --port 22 --cidr "$MY_IP_CIDR"
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" \
    --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" \
    --protocol tcp --port 443 --cidr 0.0.0.0/0
echo "==> App security group: $APP_SG_ID"

INFERENCE_SG_ID=$(aws ec2 create-security-group \
    --group-name vlm-inference-sg \
    --description "Inference tier: port 8000 from app tier only, SSH from admin IP" \
    --vpc-id "$VPC_ID" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$INFERENCE_SG_ID" \
    --protocol tcp --port 8000 --source-group "$APP_SG_ID"
aws ec2 authorize-security-group-ingress --group-id "$INFERENCE_SG_ID" \
    --protocol tcp --port 22 --cidr "$MY_IP_CIDR"
echo "==> Inference security group: $INFERENCE_SG_ID (locked to app SG + your IP)"

# --- 4. App instance (t3.micro, free tier, on-demand) ---------------------
AL2023_AMI=$(aws ssm get-parameters \
    --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query 'Parameters[0].Value' --output text)

sed "s#__REPO_URL__#${REPO_URL}#" infra/scripts/app-instance-userdata.sh > /tmp/app-userdata.sh

APP_INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AL2023_AMI" \
    --instance-type "$APP_INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$APP_SG_ID" \
    --user-data file:///tmp/app-userdata.sh \
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=vlm-app}]' \
    --query 'Instances[0].InstanceId' --output text)
echo "==> App instance launched: $APP_INSTANCE_ID"

EIP_ALLOC_ID=$(aws ec2 allocate-address --domain vpc \
    --query 'AllocationId' --output text)
aws ec2 wait instance-running --instance-ids "$APP_INSTANCE_ID"
aws ec2 associate-address --instance-id "$APP_INSTANCE_ID" --allocation-id "$EIP_ALLOC_ID" > /dev/null
EIP_ADDRESS=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC_ID" \
    --query 'Addresses[0].PublicIp' --output text)
echo "==> Elastic IP: $EIP_ADDRESS"
DOTTED_IP=$(echo "$EIP_ADDRESS" | tr '.' '-')
echo "==> Your public URL will be: https://vlm-cards.${DOTTED_IP}.sslip.io"
echo "    (set this as APP_DOMAIN in the app instance's .env — see docs/DEPLOY.md)"

# --- 5. GPU inference instance (g4dn.xlarge, persistent spot) -------------
echo "==> Looking up latest Deep Learning OSS Nvidia Driver AMI..."
GPU_AMI=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=Deep Learning OSS Nvidia Driver AMI GPU PyTorch*" \
              "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)

if [ -z "$GPU_AMI" ] || [ "$GPU_AMI" == "None" ]; then
    echo "!! Could not find a Deep Learning AMI automatically."
    echo "!! Search the EC2 AMI catalog for 'Deep Learning OSS Nvidia Driver AMI' and set GPU_AMI manually."
else
    echo "==> Using GPU AMI: $GPU_AMI"
    GPU_INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$GPU_AMI" \
        --instance-type "$GPU_INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$INFERENCE_SG_ID" \
        --instance-market-options '{"MarketType":"spot","SpotOptions":{"SpotInstanceType":"persistent","InstanceInterruptionBehavior":"stop"}}' \
        --user-data file://infra/scripts/gpu-instance-userdata.sh \
        --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":75,"VolumeType":"gp3"}}]' \
        --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=vlm-gpu-inference}]' \
        --query 'Instances[0].InstanceId' --output text 2>&1) \
        && echo "==> GPU spot instance launched: $GPU_INSTANCE_ID" \
        || echo "!! GPU instance launch failed — likely the vCPU quota is still 0. See infra/scripts/request-gpu-quota.sh and docs/DEPLOY.md Phase 0. Fall back to cpu-instance-userdata.sh (t3.large, no quota needed) in the meantime."
fi

cat <<EOF

==========================================================================
DONE. Summary:
  App instance:        $APP_INSTANCE_ID
  App public IP:        $EIP_ADDRESS
  App URL (once .env is set and DNS/cert warm up):
      https://vlm-cards.${DOTTED_IP}.sslip.io
  App security group:  $APP_SG_ID
  Inference sec. group: $INFERENCE_SG_ID
  SSH:                  ssh -i ${KEY_NAME}.pem ec2-user@${EIP_ADDRESS}

Next steps (see docs/DEPLOY.md "After provisioning"):
  1. SSH into the app instance, edit /opt/vlm-business-card/.env with the
     real VLM_PRIMARY_BASE_URL (the GPU/CPU instance's private IP), a real
     VLM_FALLBACK_API_KEY, and APP_DOMAIN.
  2. cd /opt/vlm-business-card && docker compose up -d
  3. curl https://vlm-cards.${DOTTED_IP}.sslip.io/api/health
==========================================================================
EOF
