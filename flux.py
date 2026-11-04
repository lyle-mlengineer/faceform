import os
from openai import OpenAI

# Initialize client pointing to the provider's API route
client = OpenAI(
    base_url="https://openrouter.ai",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

response = client.images.generate(
    model="black-forest-labs/flux-3-image-klein",
    prompt="A surreal floating island with waterfalls cascading into the clouds, 8k resolution",
    n=1,
    size="1024x1024"
)

# Extract and print the generated image URL
image_url = response.data[0].url
print(f"Generated Image URL: {image_url}")