import io
from google import genai
from PIL import Image
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env file

# Automatically grabs GEMINI_API_KEY from environment variables
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

prompt = "A high-quality, photorealistic cinematic shot of a red futuristic sports car driving through a neon-lit cyberpunk city at night."

print("Generating image...")
response = client.models.generate_content(
    model='gemini-3.1-flash-image',
    contents=prompt,
)

# Extract and save the generated image data
for part in response.candidates[0].content.parts:
    if part.inline_data:
        image_bytes = part.inline_data.data
        image = Image.open(io.BytesIO(image_bytes))
        image.save("generated_car.png")
        print("Success! Image saved as 'generated_car.png'.")
