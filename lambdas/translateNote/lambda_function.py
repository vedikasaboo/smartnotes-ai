import json
import os
import urllib.error
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client("s3", region_name="ap-southeast-2", config=Config(signature_version="s3v4"))
translate = boto3.client("translate")
polly = boto3.client("polly")
db = boto3.resource("dynamodb")
notes = db.Table("SmartNotes-Notes")
groups = db.Table("SmartNotes-Groups")
BUCKET = "smartnotes-sr-20261010"

LANGS = {"hi": "Hindi", "te": "Telugu", "ta": "Tamil"}
# Polly only has a Hindi voice of these three (Kajal also speaks Indian English).
# Telugu and Tamil are read aloud by the browser's own voice instead.
SPOKEN = {"hi": {"VoiceId": "Kajal", "Engine": "neural", "LanguageCode": "hi-IN"}}

# Amazon Translate is blocked in this AWS organization, so Groq is the backup.
# Both are set as environment variables on this Lambda (never in the code).
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


class TranslateError(Exception):
    pass


def chunks(text, size=2000):
    """Split on paragraph breaks so each request stays small."""
    out, current = [], ""
    for para in text.split("\n"):
        if current and len(current) + len(para) > size:
            out.append(current)
            current = ""
        current += para + "\n"
    if current.strip():
        out.append(current)
    return out


def groq_translate(text, language):
    if not GROQ_KEY:
        raise TranslateError("Translation is turned off in this AWS account.")
    parts = []
    for piece in chunks(text):
        options = {"model": GROQ_MODEL, "temperature": 0.2}
        if GROQ_MODEL.startswith("openai/gpt-oss"):
            options["reasoning_effort"] = "low"   # translation needs little "thinking"; saves time and free quota
        request = urllib.request.Request(
            GROQ_URL,
            data=json.dumps({
                **options,
                "messages": [
                    {"role": "system", "content":
                        f"Translate the user's class notes from English into {language}. "
                        "Keep technical terms (like deadlock, VPC, SQL) in English where that is "
                        "how students would say them. Keep the line breaks. "
                        "Reply with only the translation."},
                    {"role": "user", "content": piece},
                ],
            }).encode("utf-8"),
            headers={"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json",
                     "User-Agent": "smartnotes"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as resp:
                parts.append(json.loads(resp.read())["choices"][0]["message"]["content"].strip())
        except urllib.error.HTTPError as e:
            print("Groq error", e.code, e.read()[:500])
            if e.code == 429:
                raise TranslateError("The translator is busy. Try again in a minute.")
            raise TranslateError("Translation failed. Try again later.")
        except urllib.error.URLError as e:
            print("Groq unreachable", e)
            raise TranslateError("Translation failed. Try again later.")
    return "\n".join(parts)


def reply(code, data):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=str),
    }


def audio_url(bucket, note_id, lang, text):
    """MP3 of the translation (made once, then reused), or None if Polly has no voice for it."""
    if lang not in SPOKEN:
        return None
    key = f"translated/{note_id}-{lang}.mp3"
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
        try:
            audio = polly.synthesize_speech(Text=text[:2900], OutputFormat="mp3", **SPOKEN[lang])
        except ClientError as e:
            print("Polly failed:", e)
            return None
        s3.put_object(Bucket=bucket, Key=key, Body=audio["AudioStream"].read(), ContentType="audio/mpeg")
    return s3.generate_presigned_url("get_object", ExpiresIn=900, Params={"Bucket": bucket, "Key": key})


def lambda_handler(event, context):
    bucket = BUCKET
    note_id = event["pathParameters"]["id"]
    lang = (event.get("queryStringParameters") or {}).get("lang")

    if lang not in LANGS and lang != "en":
        return reply(400, {"error": "lang must be en, hi, te or ta"})

    sub = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    note = notes.get_item(Key={"noteId": note_id}).get("Item")
    member = groups.get_item(
        Key={"groupId": note.get("groupId", ""), "member": "USER#" + sub}
    ).get("Item") if note and note.get("groupId") else None
    if not member or note.get("status") != "READY":
        return reply(404, {"error": "Note not found or not ready yet"})

    # English: the note's own text and the MP3 the pipeline already made
    if lang == "en":
        text = s3.get_object(Bucket=bucket, Key=note["textKey"])["Body"].read().decode("utf-8", errors="ignore")
        url = s3.generate_presigned_url(
            "get_object", ExpiresIn=900, Params={"Bucket": bucket, "Key": note["audioKey"]}
        ) if note.get("audioKey") else None
        return reply(200, {"language": "English", "text": text, "audioUrl": url})

    cached = note.get("translations", {}).get(lang)
    if cached:
        text = s3.get_object(Bucket=bucket, Key=cached)["Body"].read().decode("utf-8")
        return reply(200, {"language": LANGS[lang], "text": text,
                           "audioUrl": audio_url(bucket, note_id, lang, text)})

    english = s3.get_object(Bucket=bucket, Key=note["textKey"])["Body"].read()
    english = english[:6000].decode("utf-8", errors="ignore")

    if not english.strip():
        return reply(400, {"error": "No text was found in this note"})

    try:
        text = translate.translate_text(
            Text=english,
            SourceLanguageCode="en",
            TargetLanguageCode=lang,
        )["TranslatedText"]
    except ClientError:
        try:
            text = groq_translate(english, LANGS[lang])
        except TranslateError as e:
            return reply(503, {"error": str(e)})

    key = f"translated/{note_id}-{lang}.txt"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )

    notes.update_item(
        Key={"noteId": note_id},
        UpdateExpression="SET translations.#l = :k",
        ExpressionAttributeNames={"#l": lang},
        ExpressionAttributeValues={":k": key},
    )

    return reply(200, {"language": LANGS[lang], "text": text,
                       "audioUrl": audio_url(bucket, note_id, lang, text)})