import re
from collections import Counter

import boto3
from botocore.exceptions import ClientError

comprehend = boto3.client("comprehend")
s3 = boto3.client("s3")
tags_table = boto3.resource("dynamodb").Table("SmartNotes-Tags")

LITTLE_WORDS = ("the ", "a ", "an ", "this ", "these ", "our ", "its ")
STOP_WORDS = {
    "the", "and", "for", "that", "this", "with", "from",
    "are", "was", "were", "have", "has", "had", "not",
    "you", "your", "its", "our", "they", "their", "can",
    "will", "would", "could", "should", "into", "about",
    "then", "than", "when", "what", "where", "which",
    "who", "how", "why", "also", "been", "being",
    # short words, now that 3-letter tags (VPC, TCP, SQL) are allowed
    "but", "all", "any", "one", "two", "use", "may", "each", "used", "out",
    "get", "set", "new", "now", "per", "via", "etc", "his", "her", "him",
    "she", "let", "see", "way", "own", "too", "did", "does", "yes", "off"
}


def comprehend_tags(text):
    phrases = comprehend.detect_key_phrases(Text=text[:4500], LanguageCode="en")["KeyPhrases"]
    phrases.sort(key=lambda p: -p["Score"])
    tags = []
    for p in phrases:
        tag = p["Text"].lower().strip(" .,:;-()")
        for little in LITTLE_WORDS:
            if tag.startswith(little):
                tag = tag[len(little):]
        if p["Score"] > 0.9 and len(tag) > 3 and tag not in tags:
            tags.append(tag)
    return tags[:15]


def word_count_tags(text):
    # Backup if Comprehend is not allowed: most common long words
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9]{2,}\b", text.lower())
    counts = Counter(word for word in words if word not in STOP_WORDS)
    return [word for word, count in counts.most_common(15)]


def lambda_handler(event, context):
    text = s3.get_object(
        Bucket=event["bucket"],
        Key=f"text/{event['noteId']}.txt"
    )["Body"].read().decode("utf-8")

    event["tags"] = []
    if not text.strip():
        return event

    try:
        tags = comprehend_tags(text)
    except ClientError as e:
        print("Comprehend failed, using word counts instead:", e)
        tags = word_count_tags(text)

    # Save each phrase and each long word in it, so "deadlock" finds "deadlock detection"
    search_words = set(tags)
    for tag in tags:
        search_words.update(w for w in tag.split() if len(w) >= 3 and w not in STOP_WORDS)

    with tags_table.batch_writer() as batch:
        for word in search_words:
            batch.put_item(Item={
                "tag": word,
                "noteId": event["noteId"],
                "subject": event["subject"],
                "title": event["title"],
                "groupId": event.get("groupId", ""),
            })

    event["tags"] = tags
    return event
