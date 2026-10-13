#!/bin/bash
# Step 5: private groups with invite codes, group-admin verification, and the new website.
#   - new table SmartNotes-Groups (+ indexes), new index on SmartNotes-Notes by group
#   - role: dynamodb:DeleteItem, sns:GetSubscriptionAttributes
#   - backs up and updates 11 Lambdas, creates the "groups" Lambda and its 5 API routes
#   - existing email subscribers only get alerts for their groups from now on
#   - uploads the new website and clears the CloudFront cache
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
ACCOUNT=775545827739
API=qrhk5zy23k
SITE_BUCKET=smartnotes-site-$ACCOUNT
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"

if [ "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]; then
  echo "Wrong AWS account. Run: aws login --profile smartnotes --region ap-southeast-2"; exit 1
fi

wait_index() {  # table index
  while true; do
    s=$(aws dynamodb describe-table --table-name "$1" \
          --query "Table.GlobalSecondaryIndexes[?IndexName=='$2'].IndexStatus | [0]" --output text)
    echo "  $1 / $2: $s"; [ "$s" = "ACTIVE" ] && break; sleep 10
  done
}

echo "== 1. Groups table"
aws dynamodb create-table --table-name SmartNotes-Groups --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=groupId,AttributeType=S AttributeName=member,AttributeType=S \
                          AttributeName=code,AttributeType=S \
  --key-schema AttributeName=groupId,KeyType=HASH AttributeName=member,KeyType=RANGE \
  --global-secondary-indexes \
    'IndexName=member-index,KeySchema=[{AttributeName=member,KeyType=HASH},{AttributeName=groupId,KeyType=RANGE}],Projection={ProjectionType=ALL}' \
    'IndexName=code-index,KeySchema=[{AttributeName=code,KeyType=HASH}],Projection={ProjectionType=ALL}' \
  --query TableDescription.TableStatus --output text
aws dynamodb wait table-exists --table-name SmartNotes-Groups
wait_index SmartNotes-Groups member-index
wait_index SmartNotes-Groups code-index

echo "== 2. Notes index by group"
aws dynamodb update-table --table-name SmartNotes-Notes \
  --attribute-definitions AttributeName=groupId,AttributeType=S AttributeName=createdAt,AttributeType=S \
  --global-secondary-index-updates \
    '[{"Create":{"IndexName":"groupId-createdAt-index","KeySchema":[{"AttributeName":"groupId","KeyType":"HASH"},{"AttributeName":"createdAt","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}}]' \
  --query TableDescription.TableStatus --output text
wait_index SmartNotes-Notes groupId-createdAt-index

echo "== 3. Role permissions"
aws iam put-role-policy --role-name smartnotesrole --policy-name smartnotesaccess \
  --policy-document "file://$HERE/smartnotesaccess-policy.json"

echo "== 4. Backups + new code for existing Lambdas"
for fn in createNote searchNotes getNote translateNote moderateNote subscribe chat lexFulfill \
          startPipeline pipeTagNote pipeSaveNotify; do
  v=$(aws lambda publish-version --function-name "$fn" --description "backup before groups $(date +%F)" \
        --query Version --output text)
  echo "$fn $v" >> "$HERE/backups-groups.txt"
  aws lambda update-function-code --function-name "$fn" --zip-file "fileb://$HERE/build/$fn.zip" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$fn"
  echo "  $fn (backup v$v) updated"
done

# translation may make several Groq requests for a long note
aws lambda update-function-configuration --function-name translateNote --timeout 60 --query Timeout --output text
aws lambda wait function-updated-v2 --function-name translateNote

echo "== 5. groups Lambda"
aws lambda create-function --function-name groups --runtime python3.14 \
  --role "arn:aws:iam::$ACCOUNT:role/smartnotesrole" --handler lambda_function.lambda_handler \
  --timeout 30 --zip-file "fileb://$HERE/build/groups.zip" --query FunctionArn --output text
aws lambda wait function-active-v2 --function-name groups

echo "== 6. API routes"
AUTH=$(aws apigatewayv2 get-routes --api-id $API --query "Items[?RouteKey=='GET /notes'].AuthorizerId | [0]" --output text)
INTEG=$(aws apigatewayv2 create-integration --api-id $API --integration-type AWS_PROXY \
          --integration-uri "arn:aws:lambda:$AWS_REGION:$ACCOUNT:function:groups" \
          --payload-format-version 2.0 --query IntegrationId --output text)
for route in "GET /groups" "POST /groups" "POST /groups/join" "GET /groups/{id}/members" \
             "POST /groups/{id}/leave" "POST /groups/{id}/remove"; do
  aws apigatewayv2 create-route --api-id $API --route-key "$route" --target "integrations/$INTEG" \
    --authorization-type JWT --authorizer-id "$AUTH" --query RouteKey --output text
done
aws lambda add-permission --function-name groups --statement-id apigateway-groups \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$AWS_REGION:$ACCOUNT:$API/*/*/groups*" >/dev/null
if [ "$(aws apigatewayv2 get-stage --api-id $API --stage-name '$default' --query AutoDeploy --output text)" != "True" ]; then
  aws apigatewayv2 create-deployment --api-id $API --stage-name '$default' >/dev/null
fi

echo "== 7. Existing alert subscribers: only their groups from now on"
TOPIC=arn:aws:sns:$AWS_REGION:$ACCOUNT:new-notes
for sub in $(aws sns list-subscriptions-by-topic --topic-arn $TOPIC \
               --query "Subscriptions[?starts_with(SubscriptionArn, 'arn:')].SubscriptionArn" --output text); do
  policy=$(aws sns get-subscription-attributes --subscription-arn "$sub" --query 'Attributes.FilterPolicy' --output text)
  new=$(python3 -I -c 'import json,sys; p=json.loads(sys.argv[1]) if sys.argv[1] not in ("", "None") else {}; p.setdefault("groupId", ["none"]); print(json.dumps(p))' "$policy")
  aws sns set-subscription-attributes --subscription-arn "$sub" --attribute-name FilterPolicy --attribute-value "$new"
  echo "  $sub -> $new"
done

echo "== 8. Website"
aws s3 cp "$ROOT/site/index.html" "s3://$SITE_BUCKET/index.html" --content-type "text/html; charset=utf-8" --only-show-errors
DIST=$(aws cloudfront list-distributions --query 'DistributionList.Items[0].Id' --output text)
aws cloudfront create-invalidation --distribution-id "$DIST" --paths '/*' --query Invalidation.Status --output text

echo "Done. Backups in deploy/backups-groups.txt (undo: BACKUPS=backups-groups.txt deploy/rollback.sh)."
echo "Next: sign in, create a group, then run deploy/assign-notes.sh <INVITE_CODE> to move the old notes into it."
