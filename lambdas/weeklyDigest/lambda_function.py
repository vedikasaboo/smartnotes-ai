from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr

sns = boto3.client("sns")
notes = boto3.resource("dynamodb").Table("SmartNotes-Notes")


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    items = notes.scan(FilterExpression=Attr("createdAt").gte(week_ago) & Attr("status").eq("READY"))["Items"]
    top = sorted(items, key=lambda n: n.get("downloads", 0), reverse=True)[:10]
    lines = [f"{i + 1}. {n['title']} ({n['subject']}) - opened {n.get('downloads', 0)} times"
             for i, n in enumerate(top)] or ["No new notes this week."]
    sns.publish(TopicArn=f"arn:aws:sns:ap-southeast-2:{account}:weekly-digest",
                Subject="Smart Notes: top notes this week",
                Message="Top notes this week:\n\n" + "\n".join(lines))
    return {"sent": len(top)}