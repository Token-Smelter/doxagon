import os
from pathlib import Path

# Resolve project root
# 1. Env var has highest priority
if os.environ.get("DOXAGON_ROOT"):
    ROOT_DIR = Path(os.environ["DOXAGON_ROOT"]).resolve()
# 2. Check if current directory looks like the project root (has library/)
elif (Path.cwd() / "library").exists():
    ROOT_DIR = Path.cwd()
# 3. Fallback for editable install: ../../.. from this file
#    src/doxagon/config.py -> src/doxagon -> src -> root
else:
    ROOT_DIR = Path(__file__).parent.parent.parent.resolve()

LIBRARY_DIR = ROOT_DIR / "library"
THESES_DIR = ROOT_DIR / "theses"
# The revisioned checkpoint workspace the hosted presentation runtime serves.
# It is a store root, not a content tree: nothing is created here on demand, so
# an unprovisioned host reports that it holds no workspace.
PRESENTATION_WORKSPACE_DIR = Path(
    os.environ.get("DOXAGON_PRESENTATION_WORKSPACE", ROOT_DIR / "presentations" / "workspace")
)
DOXAI_DIR = LIBRARY_DIR / "doxai"
EVIDENCE_DIR = LIBRARY_DIR / "evidence"
DIEGESES_DIR = LIBRARY_DIR / "diegeses"
PHANTASIAI_DIR = LIBRARY_DIR / "phantasiai"
KATALEPSEIS_DIR = LIBRARY_DIR / "katalepseis"
INBOX_DIR = LIBRARY_DIR / "inbox"
EXPLORATIONS_DIR = LIBRARY_DIR / "explorations"
LOGOS_FILE = LIBRARY_DIR / "logos.yaml"
SCHEMA_FILE = LIBRARY_DIR / "schema.yaml"

CACHE_DIR = ROOT_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "graph.pkl"
HASH_FILE = CACHE_DIR / "hash.txt"
INDEX_FILE = CACHE_DIR / "index.json"
