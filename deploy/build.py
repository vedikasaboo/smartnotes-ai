"""Zip each changed Lambda into deploy/build/. Run: python3 deploy/build.py"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCTIONS = ["pipeReadText", "pipeTagNote", "getNote", "subscribe", "translateNote", "lexFulfill", "chat",
             "groups", "createNote", "searchNotes", "moderateNote", "startPipeline", "pipeSaveNotify"]
WITH_PYPDF = {"pipeReadText"}

os.makedirs(f"{ROOT}/deploy/build", exist_ok=True)
for fn in FUNCTIONS:
    out = f"{ROOT}/deploy/build/{fn}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(f"{ROOT}/lambdas/{fn}/lambda_function.py", "lambda_function.py")
        if fn in WITH_PYPDF:
            for d, _, files in os.walk(f"{ROOT}/vendor"):
                if "__pycache__" in d:
                    continue
                for f in files:
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, f"{ROOT}/vendor"))
    print(f"{fn}: {os.path.getsize(out)} bytes")
