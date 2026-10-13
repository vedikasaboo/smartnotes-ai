#!/bin/bash
# Step 3: CloudTrail "security cameras" (guide Part 13).
# Records every AWS API call in the account into a private S3 bucket. Logs are deleted after 30 days.
# The first trail's management events are free; the log bucket costs a few cents at most.
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
ACCOUNT=775545827739
TRAIL=smartnotes-trail
LOGS=smartnotes-trail-$ACCOUNT

if [ "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]; then
  echo "Wrong AWS account. Run: aws login --profile smartnotes --region ap-southeast-2"; exit 1
fi

echo "== 1. Private log bucket"
aws s3api create-bucket --bucket "$LOGS" --create-bucket-configuration LocationConstraint=$AWS_REGION >/dev/null
aws s3api put-bucket-policy --bucket "$LOGS" --policy "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Sid\": \"TrailAclCheck\", \"Effect\": \"Allow\", \"Principal\": {\"Service\": \"cloudtrail.amazonaws.com\"},
     \"Action\": \"s3:GetBucketAcl\", \"Resource\": \"arn:aws:s3:::$LOGS\",
     \"Condition\": {\"StringEquals\": {\"aws:SourceArn\": \"arn:aws:cloudtrail:$AWS_REGION:$ACCOUNT:trail/$TRAIL\"}}},
    {\"Sid\": \"TrailWrite\", \"Effect\": \"Allow\", \"Principal\": {\"Service\": \"cloudtrail.amazonaws.com\"},
     \"Action\": \"s3:PutObject\", \"Resource\": \"arn:aws:s3:::$LOGS/AWSLogs/$ACCOUNT/*\",
     \"Condition\": {\"StringEquals\": {\"s3:x-amz-acl\": \"bucket-owner-full-control\",
                                      \"aws:SourceArn\": \"arn:aws:cloudtrail:$AWS_REGION:$ACCOUNT:trail/$TRAIL\"}}}
  ]
}"
aws s3api put-bucket-lifecycle-configuration --bucket "$LOGS" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-30-days","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":30}}]}'

echo "== 2. Trail"
aws cloudtrail create-trail --name "$TRAIL" --s3-bucket-name "$LOGS" --is-multi-region-trail \
  --enable-log-file-validation --query TrailARN --output text
aws cloudtrail start-logging --name "$TRAIL"
aws cloudtrail get-trail-status --name "$TRAIL" --query IsLogging --output text
echo "Done. See it in the console: CloudTrail -> Trails -> $TRAIL (events show up within ~15 minutes)."
