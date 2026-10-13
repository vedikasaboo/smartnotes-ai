#!/bin/bash
# Step 4: CloudFormation "master blueprint" (guide Part 13).
# Uses the CloudFormation IaC generator to scan the hand-built Smart Notes resources and write a
# template describing them. Nothing is created or changed; the scan and template are free.
# Saves the template to deploy/SmartNotes-template.yaml and shows it in
# CloudFormation -> IaC generator -> SmartNotes (where "Import to stack" turns it into a stack).
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
ACCOUNT=775545827739
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]; then
  echo "Wrong AWS account. Run: aws login --profile smartnotes --region ap-southeast-2"; exit 1
fi

echo "== 1. Scan the account (takes a few minutes)"
SCAN=$(aws cloudformation start-resource-scan --query ResourceScanId --output text)
while true; do
  status=$(aws cloudformation describe-resource-scan --resource-scan-id "$SCAN" --query Status --output text)
  echo "  $status"
  [ "$status" = "COMPLETE" ] && break
  [ "$status" = "IN_PROGRESS" ] || { echo "Scan ended with $status"; exit 1; }
  sleep 20
done

echo "== 2. Pick the Smart Notes resources"
aws cloudformation list-resource-scan-resources --resource-scan-id "$SCAN" --output json > "$HERE/build/scan.json"
python3 -I - "$HERE/build/scan.json" "$HERE/build/resources.json" <<'EOF'
import json, sys
TYPES = {"AWS::Lambda::Function", "AWS::DynamoDB::Table", "AWS::S3::Bucket", "AWS::SNS::Topic",
         "AWS::SQS::Queue", "AWS::StepFunctions::StateMachine", "AWS::ApiGatewayV2::Api",
         "AWS::Cognito::UserPool", "AWS::Events::Rule", "AWS::CloudWatch::Alarm", "AWS::IAM::Role",
         "AWS::CloudFront::Distribution", "AWS::Lex::Bot", "AWS::CloudTrail::Trail"}
ONLY_ONE = {"AWS::CloudFront::Distribution", "AWS::Lex::Bot"}
NAMES = ["smartnotes", "new-notes", "ops-alerts", "weekly-digest", "qrhk5zy23k", "ap-southeast-2_kauahkedw",
         "createnote", "searchnotes", "getnote", "translatenote", "moderatenote", "subscribe", "chat",
         "lexfulfill", "startpipeline", "weeklydigest", "servicecheck", "pipecheck", "pipereadtext",
         "pipetagnote", "pipemakeaudio", "pipesavenotify", "pipemarkfailed"]
picked = []
for r in json.load(open(sys.argv[1]))["Resources"]:
    if r["ResourceType"] not in TYPES:
        continue
    ident = " ".join(str(v) for v in r["ResourceIdentifier"].values()).lower()
    if r["ResourceType"] in ONLY_ONE or any(n in ident for n in NAMES):
        picked.append({"ResourceType": r["ResourceType"], "ResourceIdentifier": r["ResourceIdentifier"]})
for p in picked:
    print("  ", p["ResourceType"], list(p["ResourceIdentifier"].values())[0])
json.dump(picked, open(sys.argv[2], "w"))
EOF

echo "== 3. Generate the template"
aws cloudformation create-generated-template --generated-template-name SmartNotes \
  --resources "file://$HERE/build/resources.json" \
  --template-configuration DeletionPolicy=RETAIN,UpdateReplacePolicy=RETAIN >/dev/null
while true; do
  status=$(aws cloudformation describe-generated-template --generated-template-name SmartNotes --query Status --output text)
  echo "  $status"
  [ "$status" = "COMPLETE" ] && break
  case "$status" in *FAILED*) aws cloudformation describe-generated-template --generated-template-name SmartNotes \
      --query StatusReason --output text; exit 1;; esac
  sleep 10
done
aws cloudformation get-generated-template --generated-template-name SmartNotes --format YAML \
  --query TemplateBody --output text > "$HERE/SmartNotes-template.yaml"
echo "Saved deploy/SmartNotes-template.yaml ($(wc -l < "$HERE/SmartNotes-template.yaml") lines)."
