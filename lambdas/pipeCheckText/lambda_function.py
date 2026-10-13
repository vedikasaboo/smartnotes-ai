
def lambda_handler(event, context):
    if event.get("textDone") is True:
        return event

    raise Exception(
        "Text extraction is incomplete. "
        "Textract is unavailable in this AWS environment."
    )
