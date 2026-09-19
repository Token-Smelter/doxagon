# Image-provider adapter contract

**BLUF:** An adapter is an executable outside the platform repository. It receives an assembled prompt and ordered reference bytes, writes a supported image, and never translates the prompt.

## Invocation

The platform invokes exactly:

```text
<exe> --prompt-file P --output DIR --image-size {1K,2K,4K} --aspect-ratio R [--source F]...
```

`P` is UTF-8 prompt text and must be sent verbatim. If the adapter reaches its provider through a surface that rewrites text — a web composer, a shell, a form field — it must verify what arrived and exit nonzero on any difference rather than repairing it: the platform hashes the prompt and a rewrite it cannot see is a silently different request. Platform-emitted prompts begin no line with whitespace, which removes the most common such rewrite. `DIR` already exists. Each `--source F` is a raw reference file in resolved closure order; its count equals the closure and never exceeds the negotiated maximum. Image size and aspect ratio are mandates: exit nonzero if either cannot be honored.

## Output and exit status

Write one or more files directly into `DIR`. The platform selects the first sorted regular file whose suffix is `.png`, `.jpg`, `.jpeg`, `.svg`, or `.webp`; it reads nothing else. Exit 0 means success. A nonzero exit means failure. If a supported file exists after a nonzero exit, it is retained as `partial_generation` for explicit human inspection and is never admitted automatically.

Write diagnostics to stderr only. The platform retains the final 400 bytes on failure. Never print credentials, tokens, signed URLs, or prompt/reference contents that contain them.

## Capabilities

`--capabilities` is optional. A conforming adapter prints this JSON and exits 0:

```json
{"schema":"doxagon.provider-capabilities/1","max_references":10,"resolutions":["1K","2K"],"aspect_ratios":["1:1","16:9"],"model":"adapter-model-id","text_rendering":true}
```

`max_references` is an integer no greater than 14. `resolutions` and `aspect_ratios` are nonempty subsets of the platform values. The platform uses valid values only to narrow its defaults. An adapter that does not implement this invocation may exit nonzero; it remains compatible and receives platform defaults.

## Environment and location

The platform passes no credentials. An adapter may load its own configuration from `~/.doxagon/providers/<name>.env` or equivalent. Put adapter executables in `~/.doxagon/providers/`; a bare configured name is resolved there before `PATH`. `DOXAGON_IMAGE_MODEL` may label a receipt.

## Conformance

Run `dox provider check --executable <exe>` to verify executability, digest, and capability schema. Run `dox provider check --executable <exe> --live --yes` to invoke the full contract once with a synthetic prompt and two 16×16 PNG references at `1K` and `1:1`. The live check can have a paid effect, never writes into a project, and removes its temporary output.

## Stub adapter

This **stub** proves only the file contract; it does not render an image. It may be used for local conformance checks.

```python
#!/usr/bin/env python3
import sys
from pathlib import Path

if sys.argv[1:] == ["--capabilities"]:
    print('{"schema":"doxagon.provider-capabilities/1","max_references":14,"resolutions":["1K","2K","4K"],"aspect_ratios":["1:1","16:9"],"model":"stub","text_rendering":false}')
    raise SystemExit(0)
output = Path(sys.argv[sys.argv.index("--output") + 1])
output.joinpath("placeholder.png").write_bytes(b"placeholder")
```

Save the file outside a repository, mark it executable with `chmod +x`, then run the conformance command above.

## Non-goals

Adapters do not translate prompt dialects, retry requests, select candidates, or fan out across providers. Those behaviors would change the exact prompt bytes or generation semantics owned by the platform.
