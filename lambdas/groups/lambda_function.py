import json
import secrets
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

sns = boto3.client("sns")
groups = boto3.resource("dynamodb").Table("SmartNotes-Groups")

# No 0/O or 1/I/L, so codes are easy to read out
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def my_groups(sub):
    rows = groups.query(
        IndexName="member-index",
        KeyConditionExpression=Key("member").eq("USER#" + sub),
    )["Items"]
    return {row["groupId"]: row for row in rows}


def get_meta(group_id):
    return groups.get_item(Key={"groupId": group_id, "member": "META"}).get("Item")


def new_code():
    while True:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(8))
        taken = groups.query(IndexName="code-index", KeyConditionExpression=Key("code").eq(code))["Items"]
        if not taken:
            return code


def sync_alerts(account, sub, email):
    """Keep a user's email alerts limited to the groups they are in."""
    topic = f"arn:aws:sns:ap-southeast-2:{account}:new-notes"
    group_ids = list(my_groups(sub)) or ["none"]
    for page in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=topic):
        for s in page["Subscriptions"]:
            if s["Endpoint"] == email and s["SubscriptionArn"].startswith("arn:"):
                attrs = sns.get_subscription_attributes(SubscriptionArn=s["SubscriptionArn"])["Attributes"]
                policy = json.loads(attrs.get("FilterPolicy") or "{}")
                policy["groupId"] = group_ids
                sns.set_subscription_attributes(
                    SubscriptionArn=s["SubscriptionArn"],
                    AttributeName="FilterPolicy",
                    AttributeValue=json.dumps(policy),
                )


def add_member(group_id, group_name, sub, email, role):
    groups.put_item(Item={
        "groupId": group_id,
        "member": "USER#" + sub,
        "sub": sub,
        "email": email,
        "role": role,
        "groupName": group_name,
        "joinedAt": datetime.now(timezone.utc).isoformat(),
    })


def summary(meta, role):
    group = {"groupId": meta["groupId"], "name": meta["name"], "role": role}
    if role == "admin":
        group["code"] = meta["code"]
    return group


def lambda_handler(event, context):
    account = context.invoked_function_arn.split(":")[4]
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub, email = claims["sub"], claims.get("email", "")
    route = event["routeKey"]
    body = json.loads(event.get("body") or "{}")
    group_id = (event.get("pathParameters") or {}).get("id")

    if route == "GET /groups":
        result = []
        for gid, row in my_groups(sub).items():
            meta = get_meta(gid)
            if meta:
                result.append(summary(meta, row["role"]))
        result.sort(key=lambda g: g["name"].lower())
        return reply(200, result)

    if route == "POST /groups":
        name = (body.get("name") or "").strip()[:60]
        if not name:
            return reply(400, {"error": "Give the group a name."})
        meta = {
            "groupId": str(uuid.uuid4()),
            "member": "META",
            "name": name,
            "code": new_code(),
            "adminSub": sub,
            "adminEmail": email,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        groups.put_item(Item=meta)
        add_member(meta["groupId"], name, sub, email, "admin")
        sync_alerts(account, sub, email)
        return reply(200, summary(meta, "admin"))

    if route == "POST /groups/join":
        code = "".join(ch for ch in (body.get("code") or "").upper() if ch.isalnum())
        found = groups.query(IndexName="code-index", KeyConditionExpression=Key("code").eq(code))["Items"] if code else []
        if not found:
            return reply(404, {"error": "No group has that code. Check it and try again."})
        meta = found[0]
        mine = my_groups(sub)
        if meta["groupId"] in mine:
            return reply(200, summary(meta, mine[meta["groupId"]]["role"]))
        add_member(meta["groupId"], meta["name"], sub, email, "member")
        sync_alerts(account, sub, email)
        return reply(200, summary(meta, "member"))

    # Everything below is about one group, so you must be in it
    me = groups.get_item(Key={"groupId": group_id, "member": "USER#" + sub}).get("Item")
    if not me:
        return reply(404, {"error": "Group not found"})

    if route == "GET /groups/{id}/members":
        rows = groups.query(
            KeyConditionExpression=Key("groupId").eq(group_id) & Key("member").begins_with("USER#")
        )["Items"]
        members = [{"sub": r["sub"], "email": r.get("email", ""), "role": r["role"]} for r in rows]
        members.sort(key=lambda m: (m["role"] != "admin", m["email"].lower()))
        return reply(200, members)

    if route == "POST /groups/{id}/leave":
        if me["role"] == "admin":
            return reply(400, {"error": "You created this group, so you can't leave it."})
        groups.delete_item(Key={"groupId": group_id, "member": "USER#" + sub})
        sync_alerts(account, sub, email)
        return reply(200, {"message": "You left the group."})

    if route == "POST /groups/{id}/remove":
        if me["role"] != "admin":
            return reply(403, {"error": "Only the group admin can remove members."})
        target = body.get("sub") or ""
        if target == sub:
            return reply(400, {"error": "You can't remove yourself."})
        row = groups.get_item(Key={"groupId": group_id, "member": "USER#" + target}).get("Item")
        if not row:
            return reply(404, {"error": "That person isn't in this group."})
        groups.delete_item(Key={"groupId": group_id, "member": "USER#" + target})
        sync_alerts(account, target, row.get("email", ""))
        return reply(200, {"message": "Removed " + row.get("email", "member") + "."})

    return reply(404, {"error": "Unknown route"})
