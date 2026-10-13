# Smart Notes service check: paste into a Lambda called "serviceCheck"
# (role: SmartNotesRole, timeout 60 seconds), Deploy, then Test with {}.
# It tries each AI service once and tells you if your account's organization blocks it.
import boto3

TESTS = {
    "Textract": lambda: boto3.client("textract").detect_document_text(Document={"Bytes": b"x"}),
    "Rekognition": lambda: boto3.client("rekognition").detect_text(Image={"Bytes": b"x"}),
    "Rekognition moderation": lambda: boto3.client("rekognition").detect_moderation_labels(Image={"Bytes": b"x"}),
    "Comprehend": lambda: boto3.client("comprehend").detect_key_phrases(Text="Deadlocks in operating systems", LanguageCode="en"),
    "Polly": lambda: boto3.client("polly").synthesize_speech(Text="hi", OutputFormat="mp3", VoiceId="Kajal", Engine="neural", LanguageCode="en-IN"),
    "Translate": lambda: boto3.client("translate").translate_text(Text="hello", SourceLanguageCode="en", TargetLanguageCode="hi"),
    "Lex": lambda: boto3.client("lexv2-runtime").recognize_text(botId="AAAAAAAAAA", botAliasId="TSTALIASID", localeId="en_US", sessionId="check", text="hi"),
}


def lambda_handler(event, context):
    results = {}
    for name, call in TESTS.items():
        try:
            call()
            results[name] = "ALLOWED"
        except Exception as e:
            msg = str(e)
            if "service control policy" in msg:
                results[name] = "BLOCKED by your organization"
            elif "AccessDenied" in msg or "not authorized" in msg:
                results[name] = "role is missing permission (fixable)"
            else:
                # Any other error (bad test image, unknown bot) means AWS let the call through.
                results[name] = "ALLOWED"
    for name, result in results.items():
        print(f"{name}: {result}")
    return results
