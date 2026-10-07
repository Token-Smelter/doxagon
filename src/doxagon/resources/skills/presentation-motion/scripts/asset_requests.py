"""Emit reviewable Doxagon requests for N animation components; never call a provider or apply."""

import argparse
import json
from pathlib import Path

from doxagon.presentations.generation import ASPECT_RATIOS
from doxagon.renderings.document_assets import key_name

ROOT = Path(__file__).resolve().parents[1]
COMMON = (
    "Transparent background with real alpha, not a checkerboard picture. "
    "No text, labels, scenery or cast shadow outside the silhouette. "
    "It must stay legible against light and dark surfaces."
)
# Role contracts fix what the animation needs; the style supplies appearance.
ROLES = {
    "layer": (
        "One registered layer of a multi-part object. Every layer uses the identical square framing, scale, "
        "three-quarter view from slightly above, and pivot. Draw only this layer's part, in its assembled "
        "position, so the layers overlay exactly into the whole object."
    ),
    "actor": "One actor that will be instanced several times. Centered, compact, readable at 80 pixels.",
    "loop": (
        "A part that rotates continuously, seen from directly above and centered on its rotation axis. "
        "Rotationally asymmetric, with one clear pointer, so each turn is visible. No baked motion blur."
    ),
    "emblem": "A closed emblem centered with generous margin, legible at 64 pixels.",
    "skin-tile": (
        "A seamless tile for a 3D surface: the left edge continues into the right and the top into the bottom. "
        "Flat and orthographic, evenly lit, one motif family spread evenly with no focal point."
    ),
    "skin-wrap": (
        "A panorama to be wrapped around a 3D object. Spread the composition evenly across the width with no single "
        "centred subject; large, simple shapes that stay readable when small; a calm top edge that may be cropped."
    ),
}
# Skins are surfaces, not isolated objects, so they replace the silhouette contract.
SKIN_COMMON = {
    "skin-tile": "Light marks on a pure black background, or real alpha, so the page can key and tint them. No text, border or vignette.",
    "skin-wrap": "Opaque and edge to edge. No text, logos, border, frame or vignette.",
}


def style_request(profile_name: str, key: str) -> dict:
    profile = json.loads((ROOT / "samples/profiles.json").read_text())[profile_name]
    return {"operation": "create-style", "key": key, "dialect": "brief/1", "definition": profile["image_direction"]}


def component_request(component: dict, key: str, style_key: str, reference: str | None = None) -> dict:
    key_name(key)
    # A wrap wants the wrapped span over its height ((width + depth) / height for a box). Providers offer fewer
    # ratios than the platform (`dox doctor` lists them); take the provider's closest to the span and let the wrap
    # crop the calm top edge.
    aspect = component.get("aspect_ratio", "1:1")
    if aspect not in ASPECT_RATIOS:
        raise ValueError(f"aspect_ratio must be one of {', '.join(sorted(ASPECT_RATIOS))}, not {aspect!r}")
    sources = ""
    if reference and component["role"] == "layer":
        sources = "sources: [{file: whole.png, role: registration and silhouette of the assembled object}]\n"
    definition = (
        f"---\ndialect: brief/1\nintent: Animation component ({component['role']})\nstyles: [{style_key}]\n{sources}"
        f"config:\n  resolution: 1K\n  aspect_ratio: '{aspect}'\n---\n"
        f"{component['description']}\n{ROLES[component['role']]}\n{SKIN_COMMON.get(component['role'], COMMON)}\n"
    )
    request = {"operation": "create", "key": key, "dialect": "brief/1", "definition": definition}
    if sources:
        request["references"] = {"whole.png": reference}
    return request


def requests(
    case: dict,
    style: str,
    prefix: str,
    slots: dict[str, str] | None = None,
    reference: str | None = None,
    style_key: str | None = None,
) -> dict[str, dict]:
    """Return file name -> request: one style, one asset per component, and the slot binding."""
    own_style = style_key is None
    style_key = style_key or key_name(f"{prefix}-{style}")
    files = {"create-style.json": style_request(style, style_key)} if own_style else {}
    keys, ratios = {}, {}
    for component in case["components"]:
        ratios[component["key"]] = component.get("aspect_ratio", "1:1")
        keys[component["key"]] = key_name(f"{prefix}-{component['key']}")
        files[f"create-{component['key']}.json"] = component_request(
            component, keys[component["key"]], style_key, reference
        )
    complete = slots and set(slots) == set(keys)
    associations = {(slots[name] if complete else f"SLOT_FOR_{name.upper()}"): key for name, key in keys.items()}
    files["bind-slots.json" if complete else "bind-slots.template.json"] = {
        "operation": "bind-slots",
        "associations": associations,
    }
    files["sequence.json"] = {
        "paid_effect": False,
        "steps": (["Plan, review and apply create-style.json"] if own_style else [])
        + [f"Refresh context; plan, review and apply create-{name}.json" for name in keys]
        + [
            f"dox document generation-plan --asset {key} --variants 1 --resolution 1k --aspect-ratio {ratios[name]}"
            for name, key in keys.items()
        ]
        + [
            "Review every assembled prompt, then run approved plans with generation-run",
            "Inspect transparent components with check_alpha.py; record any derived matte as an admitted derivative",
            "Review skins as surfaces: tile skin-tile 2 x 2 for seams; preview skin-wrap on its part",
            "Bind stable image slots, then select-image per component",
        ],
        "assets": keys,
    }
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "samples/inspection.json")
    parser.add_argument(
        "--style", choices=list(json.loads((ROOT / "samples/profiles.json").read_text())), required=True
    )
    parser.add_argument("--prefix", required=True, help="Asset key prefix, for example harbor-motion")
    parser.add_argument("--style-key", help="Use an already registered project style instead of a teaching profile")
    parser.add_argument("--slot", action="append", default=[], metavar="COMPONENT=SLOT_ID")
    parser.add_argument("--reference-item", help="Inspection item id of the assembled object, used to register layers")
    parser.add_argument("--output", type=Path, required=True, help="New directory for review; nothing is executed")
    args = parser.parse_args()
    slots = dict(item.split("=", 1) for item in args.slot) or None
    files = requests(
        json.loads(args.case.read_text()), args.style, args.prefix, slots, args.reference_item, args.style_key
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "files": sorted(files), "paid_effect": False, "applied": False}))
