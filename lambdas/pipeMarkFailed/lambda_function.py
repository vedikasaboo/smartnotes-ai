import boto3

notes = boto3.resource("dynamodb").Table("SmartNotes-Notes")


def lambda_handler(event, context):
    notes.update_item(
        Key={"noteId": event["noteId"]},
        UpdateExpression="SET #s = :f",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":f": "FAILED"},
    )
    return event