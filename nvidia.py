import requests
import base64
import os
from PIL import Image
from io import BytesIO

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_KEY = os.environ.get("NVIDIA_API_KEY")
invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux-3-image-klein"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}

payload = {
    "prompt": "A candid photograph from the wings of a theater, looking out at ballet dancers performing Swan Lake. Dark, blurred onlookers fill the foreground; on stage, ballerinas in white tutus are caught mid-motion under a strong central spotlight. Deep blacks, shadowy purples, and stark white. Grainy mid-20th-century color film, shallow depth of field.",
    "width": 1024,
    "height": 1024,
    "seed": 0,
    "steps": 50
}

response = requests.post(invoke_url, headers=headers, json=payload)

response.raise_for_status()
response_body = response.json()
base64_image_data = response_body["artifacts"][0]["base64"]

# 5. Decode the base64 string into binary image data
image_bytes = base64.b64decode(base64_image_data)

# 6. Open with Pillow and save locally
image = Image.open(BytesIO(image_bytes))
output_path = "nvidia_generated_image.png"
image.save(output_path)
print(f"Image successfully saved to {output_path}")