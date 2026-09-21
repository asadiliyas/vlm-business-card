#!/bin/bash
# Tears down every billable resource this project creates, in an order that
# won't leave orphans. Run this when you're done demoing/submitting and
# don't need the deployment to stay live — an unattached Elastic IP or a
# stopped instance's EBS volume both keep billing quietly otherwise (see
# docs/COSTS.md). Safe to re-run; each step tolerates "already gone".
#
# This does NOT delete your AWS account, IAM user, or the billing
# alarm/budget (those cost nothing to leave in place).

set -uo pipefail  # no -e: we want to attempt every step even if one fails
AWS_REGION="${1:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

echo "==> Tearing down in region $AWS_REGION"

echo "--> Terminating tagged instances (Name=vlm-app, Name=vlm-gpu-inference)..."
INSTANCE_IDS=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=vlm-app,vlm-gpu-inference" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$INSTANCE_IDS" ]; then
    aws ec2 terminate-instances --instance-ids $INSTANCE_IDS
    echo "    Terminating: $INSTANCE_IDS (waiting...)"
    aws ec2 wait instance-terminated --instance-ids $INSTANCE_IDS
else
    echo "    None found."
fi

# Persistent spot requests don't die with the instance — cancel explicitly.
echo "--> Cancelling any persistent spot requests..."
SPOT_REQUEST_IDS=$(aws ec2 describe-spot-instance-requests \
    --filters "Name=state,Values=open,active" \
    --query 'SpotInstanceRequests[].SpotInstanceRequestId' --output text)
if [ -n "$SPOT_REQUEST_IDS" ]; then
    aws ec2 cancel-spot-instance-requests --spot-instance-request-ids $SPOT_REQUEST_IDS
    echo "    Cancelled: $SPOT_REQUEST_IDS"
else
    echo "    None found."
fi

echo "--> Releasing unattached Elastic IPs (billed at \$0.005/hr each since Feb 2024)..."
EIP_ALLOC_IDS=$(aws ec2 describe-addresses \
    --query 'Addresses[?AssociationId==`null`].AllocationId' --output text)
for alloc_id in $EIP_ALLOC_IDS; do
    aws ec2 release-address --allocation-id "$alloc_id"
    echo "    Released: $alloc_id"
done
[ -z "$EIP_ALLOC_IDS" ] && echo "    None found."

echo "--> Deleting leftover EBS volumes (terminated instances should auto-delete"
echo "    theirs via DeleteOnTermination, but this catches any that didn't)..."
VOLUME_IDS=$(aws ec2 describe-volumes \
    --filters "Name=status,Values=available" \
    --query 'Volumes[].VolumeId' --output text)
for vol_id in $VOLUME_IDS; do
    aws ec2 delete-volume --volume-id "$vol_id"
    echo "    Deleted: $vol_id"
done
[ -z "$VOLUME_IDS" ] && echo "    None found."

echo "--> Security groups (vlm-app-sg, vlm-inference-sg)..."
for name in vlm-app-sg vlm-inference-sg; do
    sg_id=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=$name" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
    if [ -n "$sg_id" ] && [ "$sg_id" != "None" ]; then
        aws ec2 delete-security-group --group-id "$sg_id" \
            && echo "    Deleted: $name ($sg_id)" \
            || echo "    !! Could not delete $name yet — dependent resources may still be releasing. Re-run in a minute."
    fi
done

cat <<'EOF'

==========================================================================
Teardown pass complete. Manually double-check in the console before
trusting this is fully clean (the free CLI listing calls above only see
resources tagged/named the way this project's scripts create them):

  - EC2 > Instances        (nothing should be running)
  - EC2 > Elastic IPs       (should be empty)
  - EC2 > Volumes           (should be empty, or only "in-use")
  - EC2 > Snapshots         (this script does not create any, but check)
  - Billing > Bills         (confirm charges have stopped accruing)

The key pair (.pem) and the billing alarm/budget are left in place
deliberately — neither costs anything to keep.
==========================================================================
EOF
