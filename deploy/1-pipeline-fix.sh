#!/bin/bash
# Step 1: fix the upload pipeline and the website's Lambdas.
#   - saves a backup version of every Lambda it changes (see rollback.sh)
#   - adds rekognition:DetectText to smartnotesrole
#   - uploads new code for 6 Lambdas
#   - re-runs the two failed "vpc peering" notes and tests photo reading
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
ACCOUNT=775545827739
BUCKET=smartnotes-sr-20261010
MACHINE=arn:aws:states:$AWS_REGION:$ACCOUNT:stateMachine:SmartNotesPipeline
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]; then
  echo "Wrong AWS account. Run: aws login --profile smartnotes --region ap-southeast-2"; exit 1
fi

FUNCTIONS="pipeReadText pipeTagNote getNote subscribe translateNote lexFulfill"

echo "== 1. Backups"
for fn in $FUNCTIONS; do
  v=$(aws lambda publish-version --function-name "$fn" \
        --description "backup before fix $(date +%F)" --query Version --output text)
  echo "$fn $v" | tee -a "$HERE/backups.txt"
done

echo "== 2. Role permission (rekognition:DetectText)"
aws iam put-role-policy --role-name smartnotesrole --policy-name smartnotesaccess \
  --policy-document "file://$HERE/smartnotesaccess-policy.json"

echo "== 3. New code"
for fn in $FUNCTIONS; do
  aws lambda update-function-code --function-name "$fn" \
    --zip-file "fileb://$HERE/build/$fn.zip" --query LastUpdateStatus --output text >/dev/null
  aws lambda wait function-updated-v2 --function-name "$fn"
  echo "$fn updated"
done
# pypdf needs a bit more memory than the 128 MB default for bigger PDFs
aws lambda update-function-configuration --function-name pipeReadText --memory-size 512 \
  --query MemorySize --output text
aws lambda wait function-updated-v2 --function-name pipeReadText

echo "== 4. Photo test (Rekognition reads notes/test1.jpg)"
sleep 10   # give the new role permission a moment to take effect
aws lambda invoke --function-name pipeReadText --cli-binary-format raw-in-base64-out \
  --payload "{\"noteId\":\"selftest-image\",\"bucket\":\"$BUCKET\",\"key\":\"notes/test1.jpg\",\"fileType\":\"image\",\"subject\":\"General\",\"title\":\"selftest\"}" \
  "$HERE/build/selftest.json" --query FunctionError --output text
cat "$HERE/build/selftest.json"; echo
echo "--- text Rekognition found:"
aws s3 cp "s3://$BUCKET/text/selftest-image.txt" - || true
aws s3 rm "s3://$BUCKET/text/selftest-image.txt" || true

echo "== 5. Re-run the failed notes"
EXECS=""
for id in 9c4ad8f0-69ee-41bb-ba55-7b4c8a63f930 2a3c6771-2827-4cb7-a43d-fa4fa675c203; do
  input="{\"noteId\":\"$id\",\"bucket\":\"$BUCKET\",\"key\":\"notes/$id.pdf\",\"fileType\":\"pdf\",\"subject\":\"Cloud Computing\",\"title\":\"vpc peering\"}"
  arn=$(aws stepfunctions start-execution --state-machine-arn "$MACHINE" \
          --name "rerun-$id-$(date +%s)" --input "$input" --query executionArn --output text)
  EXECS="$EXECS $arn"
done
sleep 30
for arn in $EXECS; do
  aws stepfunctions describe-execution --execution-arn "$arn" --query '[name,status]' --output text
done
aws dynamodb scan --table-name SmartNotes-Notes \
  --query 'Items[].[title.S,status.S,join(`, `, tags.L[].S || `[]`)]' --output text

echo "Done. Backup versions are listed in deploy/backups.txt (undo with deploy/rollback.sh)."
