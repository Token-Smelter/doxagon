"""Prompt loading and rendering utilities.

Prompts are stored as markdown files in the doxagon.prompts package.
Use {variable} syntax for template variables.
"""

from importlib import resources
from importlib.resources import files

import doxagon.prompts


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
    prompt_file = files(doxagon.prompts).joinpath(f"{name}.md")

    try:
        template = prompt_file.read_text()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt not found: {name}.md")
    except Exception as e:
        raise FileNotFoundError(f"Prompt not found: {name}.md ({e})")

    # Simple {variable} substitution using str.format()
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise KeyError(f"Missing template variable in prompt '{name}': {e}")


def list_prompts() -> list[str]:
    """List all available prompt names."""
    prompt_files = files(doxagon.prompts)
    return [f.name[:-3] for f in prompt_files.iterdir() if f.name.endswith('.md')]
