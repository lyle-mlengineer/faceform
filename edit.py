import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

INVOKE_URL = (
    "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-kontext-dev"
)
DEFAULT_PROMPT = "Change the blue t-shirt to a bright red t-shirt"


invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux-3-image-klein"

headers = {
    "Authorization": "Bearer $NVIDIA_API_KEY",
    "Accept": "application/json",
}

payload = {
    "prompt": "A candid photograph from the wings of a theater, looking out at ballet dancers performing Swan Lake. Dark, blurred onlookers fill the foreground; on stage, ballerinas in white tutus are caught mid-motion under a strong central spotlight. Deep blacks, shadowy purples, and stark white. Grainy mid-20th-century color film, shallow depth of field.",
    "image": ["data:image/png;example_id,0"],
    "width": 1024,
    "height": 1024,
    "seed": 0,
    "steps": 50
}

response = requests.post(invoke_url, headers=headers, json=payload)

response.raise_for_status()
response_body = response.json()
print(response_body)
