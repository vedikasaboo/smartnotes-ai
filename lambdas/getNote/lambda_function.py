import json

import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    region_name="ap-southeast-2",
    config=Config(signature_version="s3v4"),
)
db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")
BUCKET = "smartnotes-sr-20261010"


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def lambda_handler(event, context):
    bucket = BUCKET
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    note_id = event["pathParameters"]["id"]

    # Only members of the note's group can open it; hidden notes only the admin
    note = notes.get_item(Key={"noteId": note_id}).get("Item")
    member = groups.get_item(
        Key={"groupId": note.get("groupId", ""), "member": "USER#" + claims["sub"]}
    ).get("Item") if note and note.get("groupId") else None
    if not member or (note["status"] == "HIDDEN" and member["role"] != "admin"):
        return reply(404, {"error": "Note not found"})

    notes.update_item(
        Key={"noteId": note_id},
        UpdateExpression="ADD downloads :one",
        ExpressionAttributeValues={":one": 1},
    )

    note["fileUrl"] = s3.generate_presigned_url(
        "get_object",
        ExpiresIn=900,
        Params={"Bucket": bucket, "Key": note["fileKey"]},
    )

    if note.get("audioKey"):
        note["audioUrl"] = s3.generate_presigned_url(
            "get_object",
            ExpiresIn=900,
            Params={"Bucket": bucket, "Key": note["audioKey"]},
        )

    return reply(200, note)