"""The executables a deployment runs behind the presentation seams.

`doxagon.presentations` deliberately holds no execution facility: it validates
author-controlled source, and a validator that could start a process is a
validator that could be made to run what it is checking
(`tests/test_presentations_v2.py` enforces that by import). The two seams it
declares — `generation.ImageGenerator` and `authoring.AgentAuthor` — are
therefore implemented here, one module outside that boundary, where running a
configured executable is the whole point.

Both implementations are the same shape: a command this deployment named, the
request written across a documented interface, and the answer read back. Neither
invents an artifact. A backend that exits non-zero, times out, or answers with
nothing raises, and the caller records that as the failure it is.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence

from .presentations.authoring import AgentAuthor, AuthoringRequest
from .presentations.errors import WorkspaceError
from .presentations.generation import GeneratedImage, ImageGenerator, GeneratorInput, generator_argv

#: The image media types a produced file may carry, keyed by the suffix the
#: generator wrote. A backend that answers with anything else is refused by name
#: rather than admitted as bytes no validator would accept.
GENERATED_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


class PartialImageGeneration(WorkspaceError):
    """A failed invocation returned one bounded candidate for inspection."""

    def __init__(self, image: GeneratedImage):
        super().__init__('PRES_GENERATION_PARTIAL', 'The generator failed after returning a candidate')
        self.image = image


def _partial_candidate(outputs: Path) -> GeneratedImage | None:
    for path in sorted(outputs.iterdir()):
        if (not path.is_symlink() and path.is_file() and path.suffix.lower() in GENERATED_MEDIA_TYPES
                and 0 < path.stat().st_size <= 32 * 1024 * 1024):
            return GeneratedImage(path.read_bytes(), GENERATED_MEDIA_TYPES[path.suffix.lower()])
    return None


@dataclass(frozen=True)
class SubprocessImageGenerator:
    """Run a configured external generator once per planned variant.

    The executable is named by deployment and receives the assembled prompt and
    the reference closure through `generator_argv` — the same argv contract the
    legacy generation path used — and answers with image files in the output
    directory. Everything on this side of the seam is real: a backend that
    refuses raises, and `execute_plan` records that as this variant's failure
    instead of admitting a placeholder asset.
    """

    executable: str
    timeout_seconds: float = 600.0

    def __call__(self, variant: GeneratorInput, references: Sequence[bytes]) -> GeneratedImage:
        with TemporaryDirectory(prefix="doxagon-generation-") as scratch:
            workspace = Path(scratch)
            prompt_file = workspace / "prompt.txt"
            prompt_file.write_text(variant.prompt.text, encoding="utf-8")
            outputs = workspace / "outputs"
            outputs.mkdir()
            reference_files = []
            for index, data in enumerate(references):
                path = workspace / f"reference-{index:02d}"
                path.write_bytes(data)
                reference_files.append(str(path))
            argv = generator_argv(self.executable, variant, str(prompt_file), str(outputs), reference_files)
            try:
                completed = subprocess.run(  # noqa: S603 - the executable is deployment configuration
                    argv, capture_output=True, timeout=self.timeout_seconds, check=False
                )
            except (OSError, subprocess.SubprocessError) as error:
                partial = _partial_candidate(outputs)
                if partial:
                    raise PartialImageGeneration(partial) from error
                raise WorkspaceError(
                    "PRES_GENERATION_FAILED", f"the image generator could not be run: {error}"
                ) from error
            if completed.returncode != 0:
                partial = _partial_candidate(outputs)
                if partial:
                    raise PartialImageGeneration(partial)
                detail = completed.stderr.decode("utf-8", "replace").strip()[-400:]
                raise WorkspaceError(
                    "PRES_GENERATION_FAILED",
                    f"the image generator exited {completed.returncode}: {detail or 'no diagnostic'}",
                )
            produced = sorted(
                path
                for path in outputs.iterdir()
                if path.is_file() and path.suffix.lower() in GENERATED_MEDIA_TYPES
            )
            if not produced:
                raise WorkspaceError(
                    "PRES_GENERATION_FAILED", "the image generator produced no supported image file"
                )
            chosen = produced[0]
            return GeneratedImage(chosen.read_bytes(), GENERATED_MEDIA_TYPES[chosen.suffix.lower()])


@dataclass(frozen=True)
class SubprocessAgentAuthor:
    """Run a configured external author over one scoped task.

    The whole authoring request — the server-issued task included — is written
    to the author's stdin as JSON and the proposed source is read back from its
    stdout. A non-zero exit, a timeout, or undecodable bytes is reported as an
    authoring failure; none of them becomes a proposal.
    """

    executable: str
    timeout_seconds: float = 300.0

    @property
    def author_id(self) -> str:
        return f"subprocess:{Path(self.executable).name}"

    def __call__(self, request: AuthoringRequest) -> str:
        payload = json.dumps(request.as_dict(), sort_keys=True).encode("utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 - the executable is deployment configuration
                [self.executable], input=payload, capture_output=True, timeout=self.timeout_seconds, check=False
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise WorkspaceError(
                "PRES_AGENT_AUTHOR_FAILED", f"the authoring backend could not be run: {error}", status=502
            ) from error
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()[-400:]
            raise WorkspaceError(
                "PRES_AGENT_AUTHOR_FAILED",
                f"the authoring backend exited {completed.returncode}: {detail or 'no diagnostic'}",
                status=502,
            )
        try:
            return completed.stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError(
                "PRES_AGENT_AUTHOR_FAILED", "the authoring backend answered with non-UTF-8 bytes", status=502
            ) from error


def provider_command(environ: Mapping[str, str] | None = None) -> str:
    """Read the configured provider name at the provider boundary.

    This returns one configured candidate today; callers consume the resulting
    descriptor/path rather than coupling their behavior to environment scalar
    parsing, so a provider list can be introduced here without rewriting them.
    """
    environment = os.environ if environ is None else environ
    return environment.get("DOXAGON_IMAGE_GENERATOR", "").strip()


def resolve_image_generator_path(command: str | None) -> Path | None:
    """Resolve a provider name, preferring the user-owned adapter directory."""
    command = (command or "").strip()
    if not command:
        return None
    candidate = Path(command).expanduser()
    if candidate.parent == Path("."):
        local = Path.home() / ".doxagon/providers" / command
        if local.is_file():
            return local.resolve()
        resolved = shutil.which(command)
        return Path(resolved).resolve() if resolved else None
    return candidate.resolve() if candidate.is_file() else None


def resolve_image_generator(command: str | None) -> ImageGenerator | None:
    """The configured provider seam, or none when it cannot be executed."""
    path = resolve_image_generator_path(command)
    return SubprocessImageGenerator(str(path)) if path and os.access(path, os.X_OK) else None


def resolve_agent_author(command: str | None) -> AgentAuthor | None:
    """The author this deployment configured, or none at all."""

    command = (command or "").strip()
    return None if not command else SubprocessAgentAuthor(command)
