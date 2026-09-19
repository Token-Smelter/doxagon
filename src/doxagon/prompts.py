"""Prompt loading and rendering utilities.

Prompts are stored as markdown files in src/doxagon/prompts/.
Use {variable} syntax for template variables.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template and render with variables.

    Args:
        name: Prompt name (without extension). E.g., "dedup" loads "dedup.md"
        **kwargs: Template variables to substitute

    Returns:
        Rendered prompt string

    Raises:
        FileNotFoundError: If prompt file doesn't exist
        KeyError: If a required template variable is missing
    """
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_file}")

    template = prompt_file.read_text()

    # Simple {variable} substitution using str.format()
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise KeyError(f"Missing template variable in prompt '{name}': {e}")


def list_prompts() -> list[str]:
    """List all available prompt names."""
    return [f.stem for f in PROMPTS_DIR.glob("*.md")]
