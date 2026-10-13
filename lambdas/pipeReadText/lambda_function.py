import io

import boto3
from pypdf import PdfReader

# Textract is blocked in this AWS organization, so:
#   photos -> Rekognition DetectText (reads up to ~100 words per image)
#   PDFs   -> pypdf (works for typed PDFs, not scanned ones)
rekognition = boto3.client("rekognition")
s3 = boto3.client("s3")


def read_image(event):
    found = rekognition.detect_text(
        Image={"S3Object": {"Bucket": event["bucket"], "Name": event["key"]}}
    )["TextDetections"]
    return "\n".join(t["DetectedText"] for t in found if t["Type"] == "LINE")


def read_pdf(data):
    pages = PdfReader(io.BytesIO(data)).pages
    return "\n".join((page.extract_text() or "") for page in pages)


def lambda_handler(event, context):
    if event["fileType"] == "image":
        text = read_image(event)
    else:
        data = s3.get_object(Bucket=event["bucket"], Key=event["key"])["Body"].read()
        if event["fileType"] == "pdf":
            text = read_pdf(data)
        else:
            text = data.decode("utf-8", errors="ignore")

    s3.put_object(
        Bucket=event["bucket"],
        Key=f"text/{event['noteId']}.txt",
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    event["textDone"] = True
    return event
