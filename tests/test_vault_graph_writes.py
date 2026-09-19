import hashlib
import json
from pathlib import Path

import pytest

from doxagon.validation import GraphIntegrityError
from doxagon.wal import WriteAheadLog, read_authority_generation
from doxagon.workspace import (
    Ready,
    RecoveryDiagnostic,
    WorkspaceOpenRequest,
    initialize_empty_vault,
    open_workspace,
)


SUPPORTS = [{"source": "d-alpha", "target": "d-beta", "type": "supports"}]


def _writable_vault(root: Path) -> Path:
    vault = initialize_empty_vault(root)
    knowledge = vault / "knowledge"
    (knowledge / "doxai").mkdir()
    for slug in ("d-alpha", "d-beta"):
        (knowledge / "doxai" / f"{slug}.md").write_text(
            f"---\nbelief: {slug} belief\ntags: [synthetic]\n---\n{slug} body\n", encoding="utf-8"
        )
    (knowledge / "schema.yaml").write_text("edge_types:\n  supports: {}\n", encoding="utf-8")
    return vault


def _request(vault: Path, cwd: Path, *, read_only: bool | None = None) -> WorkspaceOpenRequest:
    return WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=read_only,
        cli_mode=None,
        environ={},
        invocation_cwd=cwd,
        standard_config_path=cwd / "missing-config.toml",
    )


def _open_ready(vault: Path, cwd: Path, *, read_only: bool | None = None) -> Ready:
    result = open_workspace(_request(vault, cwd, read_only=read_only))
    assert isinstance(result, Ready)
    return result


def test_written_edge_is_visible_to_a_subsequent_graph_read(tmp_path: Path) -> None:
    opened = _open_ready(_writable_vault(tmp_path / "vault"), tmp_path)

    opened.services.write_edges(SUPPORTS)

    assert list(opened.services.read_graph().edges(keys=True)) == [("d-alpha", "d-beta", "supports")]
    opened.services.close()


def test_read_only_workspace_refuses_a_knowledge_write(tmp_path: Path) -> None:
    opened = _open_ready(_writable_vault(tmp_path / "vault"), tmp_path, read_only=True)

    with pytest.raises(PermissionError, match="knowledge:write"):
        opened.services.write_edges(SUPPORTS)

    opened.services.close()


def test_invalid_edge_leaves_the_authority_generation_untouched(tmp_path: Path) -> None:
    vault = _writable_vault(tmp_path / "vault")
    opened = _open_ready(vault, tmp_path)

    with pytest.raises(GraphIntegrityError):
        opened.services.write_edges([{"source": "d-alpha", "target": "d-absent", "type": "supports"}])

    assert read_authority_generation(vault) == (0, None)
    opened.services.close()


def test_second_writer_is_refused_while_the_fence_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("doxagon.wal.DEFAULT_FENCE_WAIT_SECONDS", 0.1)
    vault = _writable_vault(tmp_path / "vault")
    first = _open_ready(vault, tmp_path)

    second = open_workspace(_request(vault, tmp_path))

    assert isinstance(second, RecoveryDiagnostic) and second.diagnostic == "writer_fence_unavailable"
    first.services.close()


def test_interrupted_write_rolls_forward_on_the_next_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _writable_vault(tmp_path / "vault")
    opened = _open_ready(vault, tmp_path)

    def _interrupt(self: WriteAheadLog, prepared: object) -> None:
        raise RuntimeError("simulated interruption before install")

    monkeypatch.setattr(WriteAheadLog, "_install", _interrupt)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        opened.services.write_edges(SUPPORTS)
    opened.services.close()
    monkeypatch.undo()

    reopened = _open_ready(vault, tmp_path)

    assert list(reopened.services.read_graph().edges(keys=True)) == [("d-alpha", "d-beta", "supports")]
    reopened.services.close()


def test_recovery_finalizes_a_transaction_whose_postimage_already_landed(tmp_path: Path) -> None:
    vault = _writable_vault(tmp_path / "vault")
    opened = _open_ready(vault, tmp_path)
    opened.services.write_edges(SUPPORTS)
    generation, _ = read_authority_generation(vault)
    txid = "0" * 32
    wal_root = vault / ".doxagon" / "wal"
    wal_root.mkdir(parents=True, exist_ok=True)
    (wal_root / f"{txid}.json").write_text(
        json.dumps(
            {
                "format": 1,
                "txid": txid,
                "kind": "replace",
                "target": "knowledge/logos.yaml",
                "postimage": f"knowledge/.doxagon-stage/{txid}.postimage",
                "sha256": hashlib.sha256((vault / "knowledge" / "logos.yaml").read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (vault / ".doxagon" / "authority-generation.json").write_text(
        json.dumps({"format": 1, "generation": generation + 1, "active_txid": txid}), encoding="utf-8"
    )
    opened.services.close()

    reopened = _open_ready(vault, tmp_path)

    assert read_authority_generation(vault) == (generation + 2, None)
    reopened.services.close()
