import boto3

rekognition = boto3.client("rekognition")
notes = boto3.resource("dynamodb").Table("SmartNotes-Notes")


def lambda_handler(event, context):
    event["safe"] = True
    if event["fileType"] == "image":
        labels = rekognition.detect_moderation_labels(
            Image={"S3Object": {"Bucket": event["bucket"], "Name": event["key"]}},
            MinConfidence=80,
        )["ModerationLabels"]
        if labels:
            event["safe"] = False
            notes.update_item(
                Key={"noteId": event["noteId"]},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "HIDDEN"},
            )
    return event