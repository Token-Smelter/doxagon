"""Serve the built product on loopback, with an empty disposable content root."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4188)
    args = parser.parse_args()
    if not (ROOT / "apps/web/frontend/build/index.html").is_file():
        raise SystemExit("Build apps/web/frontend first (npm ci && npm run build).")
    with tempfile.TemporaryDirectory(prefix="document-player-", dir=os.environ.get("SOURCERER_SCRATCH_DIR")) as root:
        os.environ["DOXAGON_ROOT"] = root
        os.environ.pop("DOXAGON_IMAGE_GENERATOR", None)
        os.environ.pop("DOXAGON_AGENT_AUTHOR", None)
        import uvicorn
        from apps.web.backend.main import app

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
