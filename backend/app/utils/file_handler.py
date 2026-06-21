import os
import uuid
from fastapi import UploadFile


async def save_uploaded_file(upload_file: UploadFile, upload_dir: str, subdir: str) -> str:
    target_dir = os.path.join(upload_dir, subdir)
    os.makedirs(target_dir, exist_ok=True)

    _, ext = os.path.splitext(upload_file.filename or "")
    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = os.path.join(target_dir, filename)

    contents = await upload_file.read()
    with open(target_path, "wb") as f:
        f.write(contents)

    return target_path

