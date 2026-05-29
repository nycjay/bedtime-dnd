"""Generate item sprites for inventory display using Gemini image generation."""

import os
import sys
import time
from pathlib import Path

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from google import genai
from google.genai import types
from rembg import remove

# Items to generate sprites for
ITEMS = [
    "sword",
    "shield",
    "potion",
    "scroll",
    "gem",
    "key",
    "bow",
    "staff",
    "helmet",
    "ring",
    "torch",
    "coin",
    "meat",
    "fruit",
    "berries",
    "medicine",
    "armor",
]

STYLE = (
    "Style: classic 1980s fantasy cartoon like the Dungeons & Dragons TV show, He-Man, or Ralph Bakshi. "
    "Bold black outlines, saturated colors, slight painterly shading. "
    "Single item icon on a transparent background. No text, no border, no frame. "
    "Simple, clean, recognizable silhouette suitable for a small inventory icon."
)

OUTPUT_DIR = Path(__file__).parent.parent / "static" / "sprites"


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for item in ITEMS:
        output_path = OUTPUT_DIR / f"{item}.png"
        if output_path.exists():
            print(f"  Skipping {item} (already exists)")
            continue

        prompt = f"Create a single {item} item icon for a fantasy RPG inventory. {STYLE}"
        print(f"  Generating {item}...", end=" ", flush=True)

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    clean = remove(part.inline_data.data)
                    output_path.write_bytes(clean)
                    print(f"✓ ({len(clean) // 1024}KB)")
                    break
            else:
                print("✗ (no image in response)")
        except Exception as e:
            print(f"✗ ({e})")

        time.sleep(2)  # Rate limit courtesy

    print(f"\nDone! Sprites saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
