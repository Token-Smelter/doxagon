"""Preview one copied document in the built player with server-enforced delivery limits.

Only the supplied HTML and optional notes are copied into a disposable content root.
The original vault and other running services are never mounted or modified.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


class MeasuredDelivery:
    def __init__(self, app, content, policy, bytes_per_second, latency_ms):
        self.app = app
        self.content = content
        self.policy = policy
        self.rate = bytes_per_second
        self.latency = latency_ms / 1000
        self.transfers = []

    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse, Response

        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/__proof__/transfers":
            return await JSONResponse(self.transfers)(scope, receive, send)
        measured = "/authored-document/render/" in path or path == "/sample.html"
        if not measured:
            return await self.app(scope, receive, send)
        record = {
            "id": uuid.uuid4().hex,
            "path": path,
            "bytes_sent": 0,
            "content_length": None,
            "elapsed_ms": 0,
            "complete": False,
            "rate_bytes_per_second": self.rate,
            "chunks": [],
        }
        self.transfers.append(record)
        self.transfers[:] = self.transfers[-30:]
        started = time.monotonic()
        await asyncio.sleep(self.latency)

        async def measured_send(message):
            if message["type"] == "http.response.start":
                headers = dict(message["headers"])
                record["content_length"] = int(headers.get(b"content-length", b"0"))
                record["status"] = message["status"]
                await send(message)
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                for offset in range(0, len(body), 16 * 1024):
                    chunk = body[offset:offset + 16 * 1024]
                    # Enforced before each write, independent of browser targets,
                    # process isolation, caches, DevTools or request interception.
                    if self.rate:
                        await asyncio.sleep(len(chunk) / self.rate)
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    record["bytes_sent"] += len(chunk)
                    record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                    record["chunks"].append([record["elapsed_ms"], record["bytes_sent"]])
                if not message.get("more_body", False):
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    record["complete"] = True
            else:
                await send(message)

        try:
            if path == "/sample.html":
                response = Response(self.content, media_type="text/html", headers={
                    "Content-Security-Policy": self.policy,
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                })
                await response(scope, receive, measured_send)
            else:
                await self.app(scope, receive, measured_send)
        finally:
            record["elapsed_ms"] = round((time.monotonic() - started) * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--port", type=int, default=4196)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--kbps", type=float, default=0, help="Document KiB/s; 512 approximates 4 Mbps; 0 is unthrottled")
    parser.add_argument("--latency-ms", type=int, default=80)
    args = parser.parse_args()
    if args.kbps < 0 or args.latency_ms < 0:
        parser.error("Delivery limits must be nonnegative")
    content = args.document.read_bytes()
    if not (ROOT / "apps/web/frontend/build/index.html").is_file():
        parser.error("Build apps/web/frontend first")
    with tempfile.TemporaryDirectory(prefix="doxagon-streaming-") as temporary:
        root = Path(temporary)
        document = root / "projects/sample/outputs/document"
        document.mkdir(parents=True)
        (root / "knowledge").mkdir()
        (root / "theses").symlink_to('projects')
        (root / "library").symlink_to('knowledge')
        (document / "sample.html").write_bytes(content)
        (root / "theses/sample/config.yaml").write_text("name: sample\ntitle: Observatory · streaming sample\n")
        selection = {"schema": "doxagon.authored-document/1", "document": "sample.html"}
        if args.notes:
            shutil.copyfile(args.notes, document / "notes.json")
            selection["notes"] = "notes.json"
        (document / "presentation.json").write_text(json.dumps(selection))
        os.environ["DOXAGON_ROOT"] = str(root)
        os.environ.pop("DOXAGON_IMAGE_GENERATOR", None)
        os.environ.pop("DOXAGON_AGENT_AUTHOR", None)
        import uvicorn
        from apps.web.backend.main import app
        from apps.web.backend.routers.authored_documents import DOCUMENT_CSP

        print(f"Sample SHA-256: {hashlib.sha256(content).hexdigest()}", flush=True)
        print(f"Player: http://{args.host}:{args.port}/present/sample", flush=True)
        print(f"Workspace: http://{args.host}:{args.port}/presentations?thesis=sample", flush=True)
        print(f"Standalone: http://{args.host}:{args.port}/sample.html", flush=True)
        wrapper = MeasuredDelivery(app, content, DOCUMENT_CSP, args.kbps * 1024, args.latency_ms)
        uvicorn.run(wrapper, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
