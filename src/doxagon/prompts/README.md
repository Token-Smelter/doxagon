# Prompts

LLM prompts are stored here as markdown files for easy editing and version control.

## Usage

```python
from doxagon.prompts import load_prompt

# Load and render a prompt with variables
prompt = load_prompt("dedup", candidate="AI is cheap", beliefs_list="...")
```

## Template Syntax

Use `{variable}` for template substitution:

```markdown
You are analyzing: {topic}

Context:
{context}
```

Variables are passed as keyword arguments to `load_prompt()`.

## Files

| Prompt | Used By | Purpose |
|--------|---------|---------|
| `dedup.md` | `dox dedup` | Semantic duplicate detection |
