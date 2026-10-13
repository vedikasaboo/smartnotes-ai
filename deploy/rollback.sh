#!/bin/bash
# Put back the code saved by 1-pipeline-fix.sh.
#   ./rollback.sh            -> roll back every function in backups.txt
#   ./rollback.sh getNote    -> roll back just one
#   BACKUPS=backups-groups.txt ./rollback.sh   -> undo the groups deploy instead
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"

# first backup line per function = the original code
awk '!seen[$1]++' "$HERE/${BACKUPS:-backups.txt}" | while read -r fn version; do
  if [ $# -gt 0 ] && [ "$fn" != "$1" ]; then continue; fi
  url=$(aws lambda get-function --function-name "$fn" --qualifier "$version" --query Code.Location --output text)
  curl -s -o "$TMP/$fn.zip" "$url"
  aws lambda update-function-code --function-name "$fn" --zip-file "fileb://$TMP/$fn.zip" \
    --query LastUpdateStatus --output text >/dev/null
  aws lambda wait function-updated-v2 --function-name "$fn"
  echo "$fn rolled back to version $version"
done
rm -rf "$TMP"
