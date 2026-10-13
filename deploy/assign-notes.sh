#!/bin/bash
# Move every note that has no group (uploaded before groups existed) into one group.
#   ./assign-notes.sh K7PX2M3Q
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
CODE="${1:?Usage: assign-notes.sh INVITE_CODE}"

GROUP=$(aws dynamodb query --table-name SmartNotes-Groups --index-name code-index \
          --key-condition-expression "code = :c" --expression-attribute-values "{\":c\":{\"S\":\"$CODE\"}}" \
          --query 'Items[0].groupId.S' --output text)
[ "$GROUP" = "None" ] && { echo "No group has code $CODE"; exit 1; }
echo "Group: $GROUP"

for id in $(aws dynamodb scan --table-name SmartNotes-Notes --filter-expression "attribute_not_exists(groupId)" \
              --query 'Items[].noteId.S' --output text); do
  aws dynamodb update-item --table-name SmartNotes-Notes --key "{\"noteId\":{\"S\":\"$id\"}}" \
    --update-expression "SET groupId = :g" --expression-attribute-values "{\":g\":{\"S\":\"$GROUP\"}}"
  # its search tags too
  for tag in $(aws dynamodb scan --table-name SmartNotes-Tags --filter-expression "noteId = :n" \
                 --expression-attribute-values "{\":n\":{\"S\":\"$id\"}}" --query 'Items[].tag.S' --output text); do
    aws dynamodb update-item --table-name SmartNotes-Tags \
      --key "{\"tag\":{\"S\":\"$tag\"},\"noteId\":{\"S\":\"$id\"}}" \
      --update-expression "SET groupId = :g" --expression-attribute-values "{\":g\":{\"S\":\"$GROUP\"}}"
  done
  echo "  moved $id"
done
