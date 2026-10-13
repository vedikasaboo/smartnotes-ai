import boto3

sns = boto3.client("sns")
db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    notes.update_item(
        Key={"noteId": event["noteId"]},
        UpdateExpression="SET #s = :r, tags = :t, textKey = :tk, audioKey = :ak",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": "READY", ":t": event["tags"],
                                   ":tk": f"text/{event['noteId']}.txt", ":ak": event["audioKey"]},
    )
    subject = event["subject"]
    # Alerts only reach people in the note's group (their filter lists their groupIds)
    group_id = event.get("groupId") or "none"
    meta = groups.get_item(Key={"groupId": group_id, "member": "META"}).get("Item") or {}
    where = f" ({meta['name']})" if meta.get("name") else ""
    sns.publish(
        TopicArn=f"arn:aws:sns:ap-southeast-2:{account}:new-notes",
        Subject=("New notes in " + subject).encode("ascii", "ignore").decode()[:99],
        Message=(f"New notes were added in {subject}{where}:\n\n  {event['title']}\n"
                 f"  Topics: {', '.join(event['tags'][:8]) or 'not detected'}\n\n"
                 "Open Smart Notes and search for it."),
        MessageAttributes={
            "subject": {"DataType": "String", "StringValue": subject},
            "groupId": {"DataType": "String", "StringValue": group_id},
        },
    )
    return event