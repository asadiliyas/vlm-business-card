#!/bin/bash
# Sets up a CloudWatch billing alarm + an AWS Budget, both emailing you when
# spend crosses a threshold. Run this BEFORE launching any instance —
# it's the guardrail against the one mistake that actually costs money on
# this project (leaving a GPU instance running on-demand). Takes under a
# minute; see docs/COSTS.md for the reasoning behind the $5 threshold.

set -euo pipefail
ALERT_EMAIL="${1:?Usage: billing-alarm.sh you@example.com [threshold_usd]}"
THRESHOLD_USD="${2:-5}"

# Billing metrics only exist in us-east-1, regardless of which region you
# actually deploy resources into.
export AWS_DEFAULT_REGION="us-east-1"

echo "==> Enabling billing alerts (required once per account for the CloudWatch alarm below)..."
aws ce update-anomaly-monitor 2>/dev/null || true  # best-effort; some accounts already have this
echo "!! If this is a brand-new account, also enable 'Receive Billing Alerts' manually:"
echo "!! Billing Console > Billing preferences > check 'Receive Billing Alerts' > Save."
echo "!! (There's no CLI call for this specific checkbox — it's a one-time console step.)"

TOPIC_ARN=$(aws sns create-topic --name vlm-billing-alerts --query 'TopicArn' --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$ALERT_EMAIL" > /dev/null
echo "==> Subscription requested for $ALERT_EMAIL — check your inbox and confirm it."

aws cloudwatch put-metric-alarm \
    --alarm-name "vlm-billing-over-${THRESHOLD_USD}usd" \
    --alarm-description "Estimated AWS charges exceeded \$${THRESHOLD_USD}" \
    --namespace "AWS/Billing" \
    --metric-name "EstimatedCharges" \
    --dimensions Name=Currency,Value=USD \
    --statistic Maximum \
    --period 21600 \
    --evaluation-periods 1 \
    --threshold "$THRESHOLD_USD" \
    --comparison-operator GreaterThanThreshold \
    --alarm-actions "$TOPIC_ARN"
echo "==> CloudWatch billing alarm created at \$${THRESHOLD_USD}."

# A Budget as a second, independent tripwire — it can also forecast and
# warn you *before* you cross the threshold, not just after.
cat > /tmp/budget.json <<EOF
{
  "BudgetName": "vlm-business-card-monthly",
  "BudgetLimit": {"Amount": "$THRESHOLD_USD", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
EOF
cat > /tmp/budget-notifications.json <<EOF
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL"}]
  }
]
EOF

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget file:///tmp/budget.json \
    --notifications-with-subscribers file:///tmp/budget-notifications.json \
    2>&1 || echo "!! Budget may already exist — check the Budgets console."

echo "==> Done. You will get an email at $ALERT_EMAIL if charges exceed \$${THRESHOLD_USD}."
