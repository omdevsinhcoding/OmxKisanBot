import os
from PIL import Image

async def process_user_thumbnail(thumb_path: str, output_path: str = "downloads/thumb.jpg") -> str:
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img = Image.open(thumb_path)
        img.convert("RGB").save(output_path, "JPEG")
        return output_path
    except Exception:
        return None
