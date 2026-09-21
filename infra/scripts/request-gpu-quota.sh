#!/bin/bash
# Files the two GPU vCPU quota increase requests a brand-new AWS account
# needs before a g4dn.xlarge (or any G/VT-family instance) can launch.
# Both default to 0 on a new account. Run this FIRST, on day one — approval
# can take anywhere from minutes to a few days, and everything else in this
# project can be built in parallel while it's pending (see PLAN.md Phase 0).
#
# Run from your own machine with `aws configure` already set up.

set -euo pipefail
AWS_REGION="${1:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
DESIRED_VCPUS="4"   # enough headroom for one g4dn.xlarge (4 vCPUs) at a time

echo "==> Region: $AWS_REGION"

# Quota codes are looked up by name rather than hardcoded, since AWS
# occasionally changes them and a wrong hardcoded code would silently
# request an increase on the wrong limit.
find_quota_code() {
    aws service-quotas list-service-quotas --service-code ec2 \
        --query "Quotas[?QuotaName=='$1'].QuotaCode" --output text
}

SPOT_QUOTA_NAME="All G and VT Spot Instance Requests"
ONDEMAND_QUOTA_NAME="Running On-Demand G and VT instances"

SPOT_CODE=$(find_quota_code "$SPOT_QUOTA_NAME")
ONDEMAND_CODE=$(find_quota_code "$ONDEMAND_QUOTA_NAME")

if [ -z "$SPOT_CODE" ]; then
    echo "!! Could not find quota code for '$SPOT_QUOTA_NAME'."
    echo "!! Browse Service Quotas > EC2 in the console and search 'G and VT' instead."
    exit 1
fi

echo "==> Requesting '$SPOT_QUOTA_NAME' -> $DESIRED_VCPUS vCPUs (code $SPOT_CODE)"
aws service-quotas request-service-quota-increase \
    --service-code ec2 --quota-code "$SPOT_CODE" \
    --desired-value "$DESIRED_VCPUS"

if [ -n "$ONDEMAND_CODE" ]; then
    echo "==> Requesting '$ONDEMAND_QUOTA_NAME' -> $DESIRED_VCPUS vCPUs (code $ONDEMAND_CODE) as backup"
    aws service-quotas request-service-quota-increase \
        --service-code ec2 --quota-code "$ONDEMAND_CODE" \
        --desired-value "$DESIRED_VCPUS"
fi

cat <<'EOF'

==> Requests filed. Track status with:
      aws service-quotas list-requested-service-quota-change-history-by-quota \
          --service-code ec2 --quota-code <code>
    or in the console: Service Quotas > Dashboard > Quota request history.

If it's rejected or still pending when you need to deploy, use
infra/scripts/cpu-instance-userdata.sh (t3.large) instead — it needs no
quota increase at all. See docs/DEPLOY.md for both paths.
EOF
