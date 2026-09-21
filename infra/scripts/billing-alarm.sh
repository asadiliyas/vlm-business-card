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

echo "!! The CloudWatch alarm below needs 'Receive Billing Alerts' enabled once per account:"
echo "!! Billing Console > Billing preferences > check 'Receive Billing Alerts' > Save."
echo "!! There's no CLI call for that specific checkbox. The AWS Budget created further down"
echo "!! does NOT depend on it and works regardless — treat the Budget as primary and the"
echo "!! CloudWatch alarm as a secondary layer that needs that one manual step to activate."

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
# warn you *before* you cross the threshold, not just after. JSON is passed
# inline (not via a file:// paramfile) — on Windows/Git Bash, an absolute
# /tmp path inside a file:// URI does not get translated to a real Windows
# path before reaching the (native, non-MSYS) aws.exe, which then fails to
# find it. Inline JSON sidesteps that entirely and works the same on Linux.
BUDGET_JSON=$(cat <<EOF
{
  "BudgetName": "vlm-business-card-monthly",
  "BudgetLimit": {"Amount": "$THRESHOLD_USD", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
EOF
)
NOTIFICATIONS_JSON=$(cat <<EOF
[
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL"}]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 50,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL"}]
  },
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
)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget "$BUDGET_JSON" \
    --notifications-with-subscribers "$NOTIFICATIONS_JSON" \
    2>&1 || echo "!! Budget may already exist — check the Budgets console."

echo "==> Done. You will get an email at $ALERT_EMAIL if charges exceed \$${THRESHOLD_USD}."
