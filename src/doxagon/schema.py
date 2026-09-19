import yaml
import sys
from doxagon.config import SCHEMA_FILE

def load_schema() -> dict:
    """Load schema from library/schema.yaml."""
    if not SCHEMA_FILE.exists():
        return {}
    return yaml.safe_load(SCHEMA_FILE.read_text()) or {}
