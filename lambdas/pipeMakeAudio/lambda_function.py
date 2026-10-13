import boto3

polly = boto3.client("polly")
s3 = boto3.client("s3")


def lambda_handler(event, context):
    text = s3.get_object(Bucket=event["bucket"], Key=f"text/{event['noteId']}.txt")["Body"].read().decode("utf-8")
    event["audioKey"] = ""
    if text.strip():
        audio = polly.synthesize_speech(Text=text[:2900], OutputFormat="mp3",
                                        VoiceId="Kajal", Engine="neural", LanguageCode="en-IN")
        key = f"audio/{event['noteId']}.mp3"
        s3.put_object(Bucket=event["bucket"], Key=key, Body=audio["AudioStream"].read(), ContentType="audio/mpeg")
        event["audioKey"] = key
    return event