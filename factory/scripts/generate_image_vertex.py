#!/usr/bin/env python3
"""Generate images using Vertex AI Gemini 3 Pro Image Preview.

An example image-provider adapter, not a supported platform path. The platform
invokes whatever `DOXAGON_IMAGE_GENERATOR` names, under the contract in
docs/image-providers.md; this script predates that seam and implements only
part of it. Copy it to ~/.doxagon/providers/ and adapt it to your own project.

Requires Google Cloud credentials (gcloud auth login) and a Vertex AI project
of your own. The platform passes no credentials and names no vendor.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
MODEL_ID = os.environ.get("DOXAGON_IMAGE_MODEL", "gemini-3-pro-image-preview")


def generate_image(prompt: str, output_dir: Path) -> Path | None:
    """Generate an image from a prompt and save to output directory."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id:
        print("❌ Set GOOGLE_CLOUD_PROJECT to your own Vertex AI project id")
        sys.exit(2)

    client = genai.Client(vertexai=True, project=project_id, location=LOCATION)

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)]
        )
    ]

    generate_content_config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
    )

    print(f"Generating image with {MODEL_ID}...")

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=generate_content_config,
    )

    # Find and save the image
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            mime_type = part.inline_data.mime_type
            ext = mime_type.split('/')[-1]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"generated_{timestamp}.{ext}"

            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'wb') as f:
                f.write(part.inline_data.data)

            print(f"✅ Image saved to: {output_file}")
            print(f"   Size: {len(part.inline_data.data):,} bytes")

            # Print usage
            print(f"\nUsage:")
            print(f"  Prompt tokens: {response.usage_metadata.prompt_token_count}")
            print(f"  Output tokens: {response.usage_metadata.candidates_token_count}")

            return output_file

    print("⚠️ No image found in response")
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate images using Vertex AI")
    parser.add_argument("--prompt-file", required=True, help="Path to prompt markdown file")
    parser.add_argument("--output", required=True, help="Output directory for generated image")
    args = parser.parse_args()

    prompt_path = Path(args.prompt_file)
    output_dir = Path(args.output)

    if not prompt_path.exists():
        print(f"❌ Prompt file not found: {prompt_path}")
        sys.exit(1)

    prompt = prompt_path.read_text()
    print(f"Read prompt from: {prompt_path}")
    print(f"Prompt length: {len(prompt)} chars\n")

    try:
        result = generate_image(prompt, output_dir)
        if result:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
