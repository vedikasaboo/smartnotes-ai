import json

import boto3
from boto3.dynamodb.conditions import Key

sns = boto3.client("sns")
groups = boto3.resource("dynamodb").Table("SmartNotes-Groups")


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    topic = f"arn:aws:sns:ap-southeast-2:{account}:new-notes"

    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    email = claims["email"]
    subjects = json.loads(event.get("body") or "{}").get("subjects") or []

    if not subjects:
        return reply(400, {"error": "Tick at least one subject"})

    # Only hear about notes in your own groups (kept up to date by the groups Lambda)
    group_ids = [row["groupId"] for row in groups.query(
        IndexName="member-index",
        KeyConditionExpression=Key("member").eq("USER#" + claims["sub"]),
    )["Items"]]
    if not group_ids:
        return reply(400, {"error": "Join or create a group first."})

    policy = json.dumps({"subject": subjects, "groupId": group_ids})

    for page in sns.get_paginator("list_subscriptions_by_topic").paginate(
        TopicArn=topic
    ):
        for sub in page["Subscriptions"]:
            if sub["Endpoint"] == email and sub["SubscriptionArn"].startswith("arn:"):
                sns.set_subscription_attributes(
                    SubscriptionArn=sub["SubscriptionArn"],
                    AttributeName="FilterPolicy",
                    AttributeValue=policy,
                )
                return reply(
                    200,
                    {"message": "Saved! You'll get emails for: " + ", ".join(subjects)},
                )

    try:
        sns.subscribe(
            TopicArn=topic,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": policy},
        )
    except sns.exceptions.InvalidParameterException:
        return reply(
            400,
            {
                "error": "Please click the confirmation link AWS emailed you first, "
                "then try again."
            },
        )

    return reply(
        200,
        {
            "message": "Almost done! Open your email and click 'Confirm subscription'."
        },
    )