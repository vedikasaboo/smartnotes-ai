import re
from collections import Counter

import boto3
from boto3.dynamodb.conditions import Key

db = boto3.resource("dynamodb")
tags = db.Table("SmartNotes-Tags")
notes = db.Table("SmartNotes-Notes")


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
    intent = event["sessionState"]["intent"]
    slot = (intent.get("slots") or {}).get("topic") or {}
    value = slot.get("value") or {}
    topic = (
        value.get("interpretedValue")
        or value.get("originalValue")
        or ""
    ).strip().lower()

    # The chat Lambda passes the asker's groups, so we only mention notes they can see
    attrs = event["sessionState"].get("sessionAttributes") or {}
    group_ids = set(filter(None, (attrs.get("groups") or "").split(",")))

    found = []
    for note_id in match_note_ids(topic, group_ids):
        note = notes.get_item(Key={"noteId": note_id}).get("Item")
        if note and note.get("status") == "READY":
            found.append(note)

    if found:
        listed = "; ".join(
            f"{note.get('title', 'Untitled')} ({note.get('subject', 'General')})" for note in found[:5]
        )
        answer = (
            f"Yes! I found {len(found)} note(s) on {topic}: {listed}. "
            f"Search '{topic}' to open them."
        )
    else:
        answer = f"Sorry, no notes on '{topic}' yet. Maybe you could upload some!"

    intent["state"] = "Fulfilled"
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": intent,
        },
        "messages": [{"contentType": "PlainText", "content": answer}],
    }
