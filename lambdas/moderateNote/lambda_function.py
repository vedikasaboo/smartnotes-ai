import json

import boto3

db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def lambda_handler(event, context):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    note_id = event["pathParameters"]["id"]

    # Only the admin of the note's group can verify or hide it
    note = notes.get_item(Key={"noteId": note_id}).get("Item")
    member = groups.get_item(
        Key={"groupId": note.get("groupId", ""), "member": "USER#" + claims["sub"]}
    ).get("Item") if note and note.get("groupId") else None
    if not member:
        return reply(404, {"error": "Note not found"})
    if member["role"] != "admin":
        return reply(403, {"error": "Only the group admin can do this"})

    if event["rawPath"].endswith("/verify"):
        notes.update_item(
            Key={"noteId": note_id},
            UpdateExpression="SET verified = :t",
            ExpressionAttributeValues={":t": True},
        )
        return reply(200, {"message": "Marked as verified"})

    notes.update_item(
        Key={"noteId": note_id},
        UpdateExpression="SET #s = :h",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":h": "HIDDEN"},
    )
    return reply(200, {"message": "Note hidden"})