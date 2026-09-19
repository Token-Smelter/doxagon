# Prompt templates directory
# Re-export from prompts.py module (which is shadowed by this directory)
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template and render with variables."""
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_file}")

    template = prompt_file.read_text()
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise KeyError(f"Missing template variable in prompt '{name}': {e}")


def list_prompts() -> list[str]:
    """List all available prompt names."""
    return [f.stem for f in PROMPTS_DIR.glob("*.md")]
