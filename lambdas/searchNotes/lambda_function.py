import json
import re
from collections import Counter

import boto3
from boto3.dynamodb.conditions import Key

db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
tags = db.Table("SmartNotes-Tags")
groups = db.Table("SmartNotes-Groups")


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


QUESTION_WORDS = {
    "the", "and", "for", "any", "are", "with", "about", "notes", "note",
    "have", "has", "what", "which", "where", "on", "of", "in", "do", "we",
}


def match_note_ids(text, group_ids):
    """Notes tagged with the whole phrase first, then notes matching the most words."""
    phrase = " ".join(text.lower().split())
    rows = tags.query(KeyConditionExpression=Key("tag").eq(phrase))["Items"] if phrase else []
    exact = [r["noteId"] for r in rows if r.get("groupId") in group_ids]

    words = [w for w in re.findall(r"[a-z0-9]+", phrase) if len(w) >= 3 and w not in QUESTION_WORDS]
    hits = Counter()
    for word in dict.fromkeys(words):
        if word == phrase:
            continue
        for r in tags.query(KeyConditionExpression=Key("tag").eq(word))["Items"]:
            if r.get("groupId") in group_ids:
                hits[r["noteId"]] += 1

    ranked = sorted(hits, key=lambda nid: -hits[nid])
    return list(dict.fromkeys(exact + ranked))


def lambda_handler(event, context):
    sub = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    qs = event.get("queryStringParameters") or {}
    mine = my_groups(sub)

    # Only search groups you're in (all of them, or the one picked)
    if qs.get("group"):
        if qs["group"] not in mine:
            return reply(403, {"error": "You're not in that group."})
        scope = {qs["group"]}
    else:
        scope = set(mine)
    if not scope:
        return reply(200, [])

    if qs.get("tag"):
        note_ids = match_note_ids(qs["tag"], scope)
        found = [notes.get_item(Key={"noteId": nid}).get("Item") for nid in note_ids]
    elif qs.get("subject"):
        found = notes.query(
            IndexName="subject-createdAt-index",
            KeyConditionExpression=Key("subject").eq(qs["subject"]),
            ScanIndexForward=False,
        )["Items"]
    else:
        found = []
        for group_id in scope:
            found += notes.query(
                IndexName="groupId-createdAt-index",
                KeyConditionExpression=Key("groupId").eq(group_id),
                ScanIndexForward=False,
                Limit=50,
            )["Items"]

    found = [
        note for note in found
        if note and note.get("status") == "READY" and note.get("groupId") in scope
    ]
    for note in found:
        member = mine[note["groupId"]]
        note["groupName"] = member.get("groupName", "")
        note["canModerate"] = member["role"] == "admin"
    if not qs.get("tag"):
        found.sort(key=lambda n: n.get("createdAt", ""), reverse=True)
    return reply(200, found)
