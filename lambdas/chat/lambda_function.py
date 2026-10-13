import json
import os
import re

import boto3
from boto3.dynamodb.conditions import Key

lex = boto3.client("lexv2-runtime")
db = boto3.resource("dynamodb")
tags = db.Table("SmartNotes-Tags")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")

BOT_ID = os.environ.get("BOT_ID", "")         # set by deploy/2-lex-bot.sh
BOT_ALIAS_ID = "TSTALIASID"                    # the built-in test alias

STOP_WORDS = {
    "what", "which", "where", "when", "have", "does", "there",
    "notes", "note", "about", "find", "show", "search", "tell",
    "me", "the", "for", "any", "are", "with", "give",
}


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data),
    }


def my_group_ids(sub):
    rows = groups.query(
        IndexName="member-index",
        KeyConditionExpression=Key("member").eq("USER#" + sub),
    )["Items"]
    return {row["groupId"] for row in rows}


def ask_lex(text, session_id, group_ids):
    # lexFulfill reads the groups from the session so it only mentions notes you can see
    resp = lex.recognize_text(
        botId=BOT_ID,
        botAliasId=BOT_ALIAS_ID,
        localeId="en_US",
        sessionId=session_id,
        text=text[:1000],
        sessionState={"sessionAttributes": {"groups": ",".join(sorted(group_ids))}},
    )
    return " ".join(m["content"] for m in resp.get("messages", []) if m.get("content"))


def search_tags(message, group_ids):
    # Backup when Lex is not set up: look the words up in the Tags table directly
    words = re.findall(r"[a-z0-9]+", message.lower())
    terms = list(dict.fromkeys(
        word for word in words
        if len(word) >= 4 and word not in STOP_WORDS
    ))[:5]

    if not terms:
        return "Please include a topic word, like deadlock."

    found = {}

    for term in terms:
        rows = tags.query(
            KeyConditionExpression=Key("tag").eq(term)
        )["Items"]

        for row in rows:
            note_id = row["noteId"]
            if note_id in found or row.get("groupId") not in group_ids:
                continue

            note = notes.get_item(
                Key={"noteId": note_id}
            ).get("Item")

            if note and note.get("status") == "READY":
                found[note_id] = note

    if found:
        note_list = "; ".join(
            f"{note.get('title', 'Untitled')} ({note.get('subject', 'General')})"
            for note in list(found.values())[:5]
        )
        return f"I found {len(found)} note(s): {note_list}. Search a topic to open them."
    return f"I couldn't find ready notes for {', '.join(terms)} yet."


def lambda_handler(event, context):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    body = json.loads(event.get("body") or "{}")
    message = (body.get("message") or "").strip()

    if not message:
        return reply(400, {"error": "Type a topic, like deadlock or paging."})

    group_ids = my_group_ids(claims["sub"])
    if not group_ids:
        return reply(200, {"reply": "Join or create a group first, then I can search its notes."})

    answer = ""
    if BOT_ID:
        try:
            answer = ask_lex(message, claims["sub"], group_ids)
        except Exception as e:
            print("Lex failed, searching tags directly instead:", e)

    return reply(200, {"reply": answer or search_tags(message, group_ids)})
