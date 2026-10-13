#!/bin/bash
# Step 2: build the SmartNotesBot Lex chatbot (guide Part 11) and connect the website's chat box to it.
#   bot -> FindNotes intent with a {topic} slot -> lexFulfill Lambda looks the topic up in SmartNotes-Tags
#   chat Lambda -> asks the bot (falls back to searching tags directly if Lex fails)
set -euo pipefail
export AWS_PROFILE=smartnotes AWS_REGION=ap-southeast-2 AWS_PAGER=""
ACCOUNT=775545827739
HERE="$(cd "$(dirname "$0")" && pwd)"
L="--bot-version DRAFT --locale-id en_US"

if [ "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]; then
  echo "Wrong AWS account. Run: aws login --profile smartnotes --region ap-southeast-2"; exit 1
fi

echo "== 1. Lex service role"
ROLE=$(aws iam list-roles --path-prefix /aws-service-role/lexv2.amazonaws.com/ \
         --query "Roles[?ends_with(RoleName, 'SmartNotesBot')].Arn | [0]" --output text)
if [ "$ROLE" = "None" ]; then
  ROLE=$(aws iam create-service-linked-role --aws-service-name lexv2.amazonaws.com \
           --custom-suffix SmartNotesBot --query Role.Arn --output text)
  sleep 10
fi
echo "$ROLE"

echo "== 2. Bot"
BOT=$(aws lexv2-models list-bots --filters name=BotName,values=SmartNotesBot,operator=EQ \
        --query 'botSummaries[0].botId' --output text)
if [ "$BOT" = "None" ]; then
  BOT=$(aws lexv2-models create-bot --bot-name SmartNotesBot --role-arn "$ROLE" \
          --data-privacy childDirected=false --idle-session-ttl-in-seconds 300 --query botId --output text)
  aws lexv2-models wait bot-available --bot-id "$BOT"
  aws lexv2-models create-bot-locale --bot-id "$BOT" $L --nlu-intent-confidence-threshold 0.40 >/dev/null
  aws lexv2-models wait bot-locale-created --bot-id "$BOT" $L
fi
echo "bot id: $BOT"

echo "== 3. TopicType slot type (expand values)"
SLOTTYPE=$(aws lexv2-models create-slot-type --bot-id "$BOT" $L --slot-type-name TopicType \
  --value-selection-setting resolutionStrategy=OriginalValue \
  --slot-type-values '[{"sampleValue":{"value":"deadlock"}},{"sampleValue":{"value":"paging"}},
    {"sampleValue":{"value":"normalization"}},{"sampleValue":{"value":"scheduling"}},
    {"sampleValue":{"value":"recursion"}},{"sampleValue":{"value":"sorting"}},
    {"sampleValue":{"value":"vpc peering"}},{"sampleValue":{"value":"subnetting"}}]' \
  --query slotTypeId --output text)

echo "== 4. FindNotes intent + topic slot"
INTENT=$(aws lexv2-models create-intent --bot-id "$BOT" $L --intent-name FindNotes --query intentId --output text)
SLOT=$(aws lexv2-models create-slot --bot-id "$BOT" $L --intent-id "$INTENT" --slot-name topic \
  --slot-type-id "$SLOTTYPE" \
  --value-elicitation-setting '{"slotConstraint":"Required","promptSpecification":{"maxRetries":2,
    "messageGroups":[{"message":{"plainTextMessage":{"value":"Which topic are you looking for?"}}}]}}' \
  --query slotId --output text)
aws lexv2-models update-intent --bot-id "$BOT" $L --intent-id "$INTENT" --intent-name FindNotes \
  --sample-utterances '[{"utterance":"do we have notes on {topic}"},{"utterance":"find notes on {topic}"},
    {"utterance":"notes about {topic}"},{"utterance":"I need {topic} notes"},
    {"utterance":"any notes on {topic}"},{"utterance":"show me {topic} notes"},{"utterance":"{topic}"}]' \
  --slot-priorities "[{\"priority\":1,\"slotId\":\"$SLOT\"}]" \
  --fulfillment-code-hook enabled=true >/dev/null

echo "== 5. Build"
aws lexv2-models build-bot-locale --bot-id "$BOT" $L >/dev/null
aws lexv2-models wait bot-locale-built --bot-id "$BOT" $L

echo "== 6. Connect lexFulfill to the test alias"
FULFILL=arn:aws:lambda:$AWS_REGION:$ACCOUNT:function:lexFulfill
aws lexv2-models update-bot-alias --bot-id "$BOT" --bot-alias-id TSTALIASID --bot-alias-name TestBotAlias \
  --bot-version DRAFT \
  --bot-alias-locale-settings "{\"en_US\":{\"enabled\":true,\"codeHookSpecification\":{\"lambdaCodeHook\":
    {\"lambdaARN\":\"$FULFILL\",\"codeHookInterfaceVersion\":\"1.0\"}}}}" >/dev/null
aws lambda add-permission --function-name lexFulfill --statement-id lex-smartnotesbot \
  --action lambda:InvokeFunction --principal lexv2.amazonaws.com \
  --source-arn "arn:aws:lex:$AWS_REGION:$ACCOUNT:bot-alias/$BOT/TSTALIASID" >/dev/null

echo "== 7. Point the chat Lambda at the bot"
aws lambda publish-version --function-name chat --description "backup before Lex $(date +%F)" \
  --query Version --output text | sed 's/^/chat /' | tee -a "$HERE/backups.txt"
aws lambda update-function-code --function-name chat --zip-file "fileb://$HERE/build/chat.zip" >/dev/null
aws lambda wait function-updated-v2 --function-name chat
aws lambda update-function-configuration --function-name chat \
  --environment "Variables={BOT_ID=$BOT}" >/dev/null
aws lambda wait function-updated-v2 --function-name chat

echo "== 8. Test"
aws lexv2-runtime recognize-text --bot-id "$BOT" --bot-alias-id TSTALIASID --locale-id en_US \
  --session-id deploy-test --text "do we have notes on peering" --query 'messages[].content' --output text
