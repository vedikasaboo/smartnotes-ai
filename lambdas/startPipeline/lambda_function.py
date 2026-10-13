import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

import boto3

sfn = boto3.client("stepfunctions")
notes = boto3.resource("dynamodb").Table("SmartNotes-Notes")


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    machine = (
        f"arn:aws:states:ap-southeast-2:{account}:"
        "stateMachine:SmartNotesPipeline"
    )

    for message in event["Records"]:
        s3_event = json.loads(message["body"])

        for record in s3_event.get("Records", []):
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(
                record["s3"]["object"]["key"]
            )
            note_id = key.split("/")[-1].rsplit(".", 1)[0]
            ext = key.rsplit(".", 1)[-1].lower()

            note = notes.get_item(
                Key={"noteId": note_id}
            ).get("Item")

            if not note:
                note = {
                    "noteId": note_id,
                    "subject": "General",
                    "title": note_id,
                    "unit": "-",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "status": "PROCESSING",
                    "fileKey": key,
                    "uploadedBy": "console",
                    "verified": False,
                    "downloads": 0,
                    "translations": {}
                }
                notes.put_item(Item=note)

            safe_name = re.sub(
                r"[^A-Za-z0-9_-]", "-", note_id
            )[:60]

            sfn.start_execution(
                stateMachineArn=machine,
                name=f"{safe_name}-{time.time_ns()}",
                input=json.dumps({
                    "noteId": note_id,
                    "bucket": bucket,
                    "key": key,
                    "fileType": "text" if ext == "txt" else ("pdf" if ext == "pdf" else "image"),
                    "subject": note["subject"],
                    "title": note["title"],
                    "groupId": note.get("groupId", "")
                })
            )