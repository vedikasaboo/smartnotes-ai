import json
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

s3 = boto3.client("s3", region_name="ap-southeast-2", config=Config(signature_version="s3v4"))
db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")
BUCKET = "smartnotes-sr-20261010"

TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    body = json.loads(event.get("body") or "{}")

    ext = body.get("fileName", "").rsplit(".", 1)[-1].lower()
    if ext not in TYPES:
        return reply(400, {"error": "Only PDF, JPG or PNG files, please."})

    max_mb = 20 if ext == "pdf" else 10
    if int(body.get("fileSize", 0)) > max_mb * 1024 * 1024:
        return reply(400, {"error": f"That file is too big (max {max_mb} MB)."})

    if not body.get("title"):
        return reply(400, {"error": "Please add a title."})

    group_id = body.get("groupId") or ""
    member = groups.get_item(Key={"groupId": group_id, "member": "USER#" + claims["sub"]}).get("Item") if group_id else None
    if not member:
        return reply(403, {"error": "Choose a group you're a member of."})

    note_id = str(uuid.uuid4())
    key = f"notes/{note_id}.{ext}"

    notes.put_item(Item={
        "noteId": note_id,
        "groupId": group_id,
        "title": body["title"][:120],
        "subject": body.get("subject") or "General",
        "unit": str(body.get("unit") or "-"),
        "semester": int(body.get("semester") or 0),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "PROCESSING",
        "fileKey": key,
        "uploadedBy": claims["sub"],
        "verified": False,
        "downloads": 0,
        "translations": {},
    })

    url = s3.generate_presigned_url(
        "put_object",
        ExpiresIn=300,
        Params={
            "Bucket": BUCKET,
            "Key": key,
            "ContentType": TYPES[ext],
        },
    )

    return reply(200, {
        "noteId": note_id,
        "uploadUrl": url,
        "contentType": TYPES[ext],
    })