"""Real-workspace lifecycle coverage for durable HTML Edition coordination."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from threading import Event, Thread
import time

from fastapi.testclient import TestClient
import pytest

from doxagon.html_editions import service
from doxagon.html_editions.api import create_html_editions_app
from doxagon.html_editions.contracts import canonical_json
from doxagon.html_editions.service import HtmlEditionCoordinator, HtmlEditionServiceError
from doxagon.workspace import initialize_empty_vault, workspace_request_for_vault


def _source() -> dict[str, object]:
    return {
        "schema": "doxagon.content-document/1",
        "document_key": "sample",
        "mode": "article",
        "metadata": {"title": "Sample Edition"},
        "theme_id": "default",
        "sections": [{"section_id": "opening", "kind": "prose", "title": "Opening", "body": "Exact document bytes."}],
        "resources": [],
        "features": {},
    }


def _workspace(tmp_path: Path) -> tuple[Path, object]:
    vault = initialize_empty_vault(tmp_path / "vault")
    document = vault / "projects" / "thesis" / "outputs" / "content-documents" / "sample"
    document.mkdir(parents=True)
    (document / "document.json").write_text(json.dumps(_source()), encoding="utf-8")
    return vault, workspace_request_for_vault(vault)


def _authority(vault: Path, generation: int) -> None:
    (vault / ".doxagon" / "authority-generation.json").write_text(
        json.dumps({"format": 1, "generation": generation, "active_txid": None}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _inventory_state(coordinator: HtmlEditionCoordinator, edition_id: str) -> bool:
    with coordinator._connection() as connection:
        return connection.execute("SELECT 1 FROM inventory WHERE edition_id=?", (edition_id,)).fetchone() is not None


def test_coordinator_idempotent_build_publishes_exact_preview_and_download(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        initial = coordinator.enqueue("thesis", "sample", "client-key")
        duplicate = coordinator.enqueue("thesis", "sample", "client-key")
        published = coordinator.run_next()
        token = coordinator.create_preview(initial.job_id)
        preview = coordinator.preview(token)
        coordinator.revoke_preview(token)
        result = (initial.job_id == duplicate.job_id, published is not None and published.state == "published", coordinator.download(initial.job_id) == preview)
    assert result == (True, True, True)


def test_idempotency_key_rejects_a_request_with_different_parameters(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        coordinator.enqueue("thesis", "sample", "client-key")
        with pytest.raises(HtmlEditionServiceError, match="idempotency key") as raised:
            coordinator.enqueue("thesis", "other", "client-key")
    assert raised.value.code == "HTML_EDITION_IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("boundary", ["artifact", "receipt", "before_inventory", "inventory"])
def test_recovery_converges_each_publish_crash_boundary(tmp_path: Path, boundary: str) -> None:
    vault, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", f"client-key-{boundary}")
        coordinator._publish_hook = lambda current: (_ for _ in ()).throw(RuntimeError("crash")) if current == boundary else None
        with pytest.raises(RuntimeError, match="crash"):
            coordinator.run_next()
        coordinator._publish_hook = None
        with coordinator._connection() as connection:
            connection.execute("UPDATE jobs SET lease_until=0 WHERE job_id=?", (job.job_id,))
        recovered = coordinator.recover()
        status = coordinator.status(job.job_id)
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (status.edition_id or "")
        result = (
            len(recovered),
            status.state,
            _inventory_state(coordinator, status.edition_id or ""),
            (edition / "edition.html").read_bytes() == coordinator.download(job.job_id),
            (edition / "receipt.json").read_bytes() == canonical_json({
                "receipt": coordinator.validate("thesis", "sample"),
                "authority_hash": coordinator._authority_hash(),
            }),
        )
    assert result == (1, "published", True, True, True)


def test_recovery_republishes_after_an_access_time_bump(tmp_path: Path) -> None:
    """An access-time bump is not artifact divergence.

    Recovery re-reads the artifact its crashed predecessor already wrote, and
    that read is itself what makes the kernel move ``st_atime`` under relatime.
    ``os.stat_result`` compares whole-second timestamps, so the bump looked like
    divergence whenever recovery landed in a later wall-clock second than the
    write. Backdating ``st_atime`` makes that boundary certain rather than
    leaving the coverage to timing.
    """

    vault, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", "atime-drift")
        coordinator._publish_hook = lambda current: (_ for _ in ()).throw(RuntimeError("crash")) if current == "before_inventory" else None
        with pytest.raises(RuntimeError, match="crash"):
            coordinator.run_next()
        coordinator._publish_hook = None
        with coordinator._connection() as connection:
            connection.execute("UPDATE jobs SET lease_until=0 WHERE job_id=?", (job.job_id,))
        artifact = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (job.edition_id or "") / "edition.html"
        modified_ns = artifact.stat().st_mtime_ns
        os.utime(artifact, ns=(modified_ns - 3_000_000_000, modified_ns))
        recovered = coordinator.recover()
        status = coordinator.status(job.job_id)
        result = (len(recovered), status.state, coordinator.download(job.job_id) == artifact.read_bytes())
    assert result == (1, "published", True)


@pytest.mark.parametrize("boundary", ["artifact", "receipt", "before_inventory"])
def test_api_cancellation_interleaves_with_running_publication(tmp_path: Path, boundary: str) -> None:
    vault, request = _workspace(tmp_path)
    app = create_html_editions_app(request)
    with TestClient(app) as client:
        coordinator = app.state.html_editions
        job = coordinator.enqueue("thesis", "sample", f"cancel-{boundary}")
        publishing = Event()
        release_publication = Event()
        cancellation_finished = Event()
        cancellation: dict[str, object] = {}

        def pause_publication(current: str) -> None:
            if current == boundary:
                publishing.set()
                assert release_publication.wait(timeout=1)

        def cancel_request() -> None:
            cancellation["response"] = client.post(f"/api/html-editions/builds/{job.job_id}/cancel")
            cancellation_finished.set()

        coordinator._publish_hook = pause_publication
        publisher_thread = Thread(target=coordinator.run_next)
        publisher_thread.start()
        assert publishing.wait(timeout=1)
        cancellation_thread = Thread(target=cancel_request)
        cancellation_thread.start()
        assert cancellation_finished.wait(timeout=1)
        release_publication.set()
        publisher_thread.join(timeout=1)
        cancellation_thread.join(timeout=1)
        response = cancellation["response"]
        status = client.get(f"/api/html-editions/builds/{job.job_id}").json()
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (status["edition_id"] or "")
        result = (
            response.status_code,
            response.json()["state"],
            not publisher_thread.is_alive(),
            not cancellation_thread.is_alive(),
            status["state"],
            _inventory_state(coordinator, status["edition_id"] or ""),
            (edition / "edition.html").exists(),
            (edition / "receipt.json").exists(),
        )
    assert result == (200, "running", True, True, "cancelled", False, False, False)


def test_same_edition_cancellation_waits_for_inventory_publication(tmp_path: Path) -> None:
    vault, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        publisher = coordinator.enqueue("thesis", "sample", "publisher-key")
        publishing = Event()
        release_publication = Event()

        def pause_before_inventory(boundary: str) -> None:
            if boundary == "before_inventory":
                publishing.set()
                release_publication.wait(timeout=1)

        coordinator._publish_hook = pause_before_inventory
        publisher_thread = Thread(target=coordinator.run_next)
        publisher_thread.start()
        assert publishing.wait(timeout=1)
        cancelled = coordinator.enqueue("thesis", "sample", "cancelled-key")
        cancellation_started = Event()

        def cancel() -> None:
            cancellation_started.set()
            coordinator.cancel(cancelled.job_id)

        cancellation_thread = Thread(target=cancel)
        cancellation_thread.start()
        assert cancellation_started.wait(timeout=1)
        cancellation_thread.join(timeout=0.05)
        cancellation_waited = cancellation_thread.is_alive()
        release_publication.set()
        publisher_thread.join(timeout=1)
        cancellation_thread.join(timeout=1)
        published = coordinator.status(publisher.job_id)
        cancelled_status = coordinator.status(cancelled.job_id)
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (published.edition_id or "")
        result = (
            cancellation_waited,
            not publisher_thread.is_alive(),
            not cancellation_thread.is_alive(),
            published.state,
            cancelled_status.state,
            _inventory_state(coordinator, published.edition_id or ""),
            (edition / "receipt.json").exists(),
            coordinator.download(publisher.job_id) == (edition / "edition.html").read_bytes(),
        )
    assert result == (True, True, True, "published", "cancelled", True, True, True)


@pytest.mark.parametrize("boundary", ["artifact", "receipt", "before_inventory"])
def test_restart_cleans_expired_cancelled_publication(tmp_path: Path, boundary: str) -> None:
    vault, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", f"expiry-cancel-{boundary}")
        coordinator._publish_hook = lambda current: (_ for _ in ()).throw(RuntimeError("crash")) if current == boundary else None
        with pytest.raises(RuntimeError, match="crash"):
            coordinator.run_next()
        coordinator.cancel(job.job_id)
        with coordinator._connection() as connection:
            connection.execute("UPDATE jobs SET lease_until=0 WHERE job_id=?", (job.job_id,))

    with HtmlEditionCoordinator.open(request) as restarted:
        recovered = restarted.recover()
        status = restarted.status(job.job_id)
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (status.edition_id or "")
        result = (
            recovered,
            status.state,
            _inventory_state(restarted, status.edition_id or ""),
            (edition / "edition.html").exists(),
            (edition / "receipt.json").exists(),
        )
    assert result == ([], "cancelled", False, False, False)


def test_stale_lease_owner_cannot_publish_after_reclaim(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", "lease-fence-key")
        stale = coordinator._claim("worker-a", 0.01)
        time.sleep(0.02)
        current = coordinator._claim("worker-b", 30.0)
        assert stale is not None and current is not None
        with pytest.raises(HtmlEditionServiceError, match="lease is no longer current"):
            coordinator._publish(stale)
        before = (coordinator.status(job.job_id).state, _inventory_state(coordinator, job.edition_id or ""))
        coordinator._publish(current)
        result = (before, coordinator.status(job.job_id).state, _inventory_state(coordinator, job.edition_id or ""))
    assert result == (("running", False), "published", True)


def test_restart_repairs_linked_temporary_artifact_after_publication_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _workspace(tmp_path)
    original_unlink = service.os.unlink

    def crash_after_link(name: str, *args: object, **kwargs: object) -> None:
        if name.startswith(".edition.html.") and name.endswith(".tmp"):
            raise RuntimeError("crash after link")
        original_unlink(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service.os, "unlink", crash_after_link)
        with HtmlEditionCoordinator.open(request) as coordinator:
            job = coordinator.enqueue("thesis", "sample", "link-crash-key")
            with pytest.raises(RuntimeError, match="crash after link"):
                coordinator.run_next()
            with coordinator._connection() as connection:
                connection.execute("UPDATE jobs SET lease_until=0 WHERE job_id=?", (job.job_id,))
    with HtmlEditionCoordinator.open(request) as restarted:
        recovered = restarted.recover()
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (job.edition_id or "")
        result = (len(recovered), restarted.status(job.job_id).state, (edition / "edition.html").stat().st_nlink, list(edition.glob(".edition.html.*.tmp")))
    assert result == (1, "published", 1, [])


def test_failed_initialization_releases_the_workspace_fence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _workspace(tmp_path)
    descriptors_before = len(list(Path("/proc/self/fd").iterdir()))
    original_open = service.os.open
    artifact_root = vault / ".doxagon" / "artifacts"

    def fail_artifact_root(path: str | Path, *args: object, **kwargs: object) -> int:
        if Path(path) == artifact_root:
            raise OSError("injected artifact-root failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service.os, "open", fail_artifact_root)
        with pytest.raises(HtmlEditionServiceError, match="configured storage root"):
            HtmlEditionCoordinator.open(request)
    with HtmlEditionCoordinator.open(request) as reopened:
        result = reopened.can_build
    descriptors_after = len(list(Path("/proc/self/fd").iterdir()))
    assert (result, descriptors_after) == (True, descriptors_before)


def test_restart_fails_stale_authority_without_artifact_or_inventory(tmp_path: Path) -> None:
    vault, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", "authority-key")
        edition_id = job.edition_id
    _authority(vault, 2)
    with HtmlEditionCoordinator.open(request) as restarted:
        recovered = restarted.recover()
        status = restarted.status(job.job_id)
        result = (len(recovered), status.state, status.error, _inventory_state(restarted, edition_id or ""), (vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (edition_id or "") / "edition.html").exists())
    assert result == (1, "failed", "HTML_EDITION_AUTHORITY_DIVERGED", False, False)


@pytest.mark.parametrize("corruption", ["unreadable", "malformed"])
def test_corrupt_authority_fails_closed_and_recovery_timer_continues(tmp_path: Path, corruption: str) -> None:
    vault, request = _workspace(tmp_path)
    app = create_html_editions_app(request, recovery_interval_seconds=0.01)
    authority = vault / ".doxagon" / "authority-generation.json"
    original_authority = authority.read_bytes()
    with TestClient(app) as client:
        coordinator = app.state.html_editions
        first = coordinator.enqueue("thesis", "sample", f"{corruption}-authority-first")
        if corruption == "unreadable":
            authority.unlink()
        else:
            authority.write_text("not json", encoding="utf-8")
        rejected = client.post(
            "/api/html-editions/builds",
            headers={"Idempotency-Key": f"{corruption}-authority-rejected"},
            json={"project": "thesis", "document": "sample"},
        )
        time.sleep(0.08)
        failed = client.get(f"/api/html-editions/builds/{first.job_id}").json()
        authority.write_bytes(original_authority)
        second = coordinator.enqueue("thesis", "sample", f"{corruption}-authority-second")
        time.sleep(0.08)
        resumed = client.get(f"/api/html-editions/builds/{second.job_id}").json()
        result = (
            rejected.status_code,
            rejected.json(),
            str(vault) not in rejected.text,
            failed["state"],
            failed["error"],
            resumed["state"],
        )
    assert result == (
        400,
        {"detail": {"code": "HTML_EDITION_AUTHORITY_UNAVAILABLE"}},
        True,
        "failed",
        "HTML_EDITION_AUTHORITY_UNAVAILABLE",
        "published",
    )


def test_publication_rejects_a_replaceable_edition_directory(tmp_path: Path) -> None:
    vault, request = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", "containment-key")
        edition = vault / ".doxagon" / "artifacts" / "html-editions" / "editions" / (job.edition_id or "")
        edition.symlink_to(outside, target_is_directory=True)
        failed = coordinator.run_next()
        result = (failed is not None and failed.error, (outside / "edition.html").exists())
    assert result == ("HTML_EDITION_STORAGE_UNSAFE", False)


def test_closed_coordinator_rejects_every_public_service_method(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    coordinator = HtmlEditionCoordinator.open(request)
    coordinator.close()
    methods = (
        lambda: coordinator.read_document("thesis", "sample"),
        lambda: coordinator.validate("thesis", "sample"),
        lambda: coordinator.resource("thesis", "sample", "asset"),
        lambda: coordinator.enqueue("thesis", "sample", "client-key"),
        lambda: coordinator.status("job-id"),
        lambda: coordinator.cancel("job-id"),
        lambda: coordinator.retry("job-id", "client-key"),
        lambda: coordinator.run_next(),
        lambda: coordinator.recover(),
        lambda: coordinator.download("job-id"),
        lambda: coordinator.create_preview("job-id"),
        lambda: coordinator.revoke_preview("token"),
        lambda: coordinator.preview("token"),
    )
    results = []
    for call in methods:
        with pytest.raises(HtmlEditionServiceError) as raised:
            call()
        results.append(raised.value.code)
    assert results == ["HTML_EDITION_CLOSED"] * len(methods)


def test_preview_expiry_and_revocation_fail_closed(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    with HtmlEditionCoordinator.open(request) as coordinator:
        job = coordinator.enqueue("thesis", "sample", "preview-key")
        coordinator.run_next()
        token = coordinator.create_preview(job.job_id, lifetime_seconds=1)
        with coordinator._connection() as connection:
            connection.execute("UPDATE preview_tokens SET expires_at=0")
        with pytest.raises(HtmlEditionServiceError, match="preview is unavailable") as expired:
            coordinator.preview(token)
        live = coordinator.create_preview(job.job_id)
        coordinator.revoke_preview(live)
        with pytest.raises(HtmlEditionServiceError, match="preview is unavailable") as revoked:
            coordinator.preview(live)
    assert (expired.value.code, revoked.value.code) == ("HTML_EDITION_PREVIEW_UNAVAILABLE", "HTML_EDITION_PREVIEW_UNAVAILABLE")


def test_readonly_lifespan_serves_document_reads_without_recovery(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    readonly = replace(request, cli_read_only=True)
    app = create_html_editions_app(readonly)
    with TestClient(app) as client:
        document = client.get("/api/html-editions/documents/thesis/sample")
        build = client.post("/api/html-editions/builds", headers={"Idempotency-Key": "client-key"}, json={"project": "thesis", "document": "sample"})
        result = (document.status_code, build.status_code)
    assert result == (200, 403)


def test_lifecycle_timer_recovers_an_expired_lease_without_a_request(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    app = create_html_editions_app(request, recovery_interval_seconds=0.01)
    with TestClient(app) as client:
        coordinator = app.state.html_editions
        job = coordinator.enqueue("thesis", "sample", "expiry-key")
        coordinator._claim("abandoned", 0.01)
        time.sleep(0.08)
        state = client.get(f"/api/html-editions/builds/{job.job_id}").json()["state"]
    assert state == "published"


def test_api_build_preview_and_download_return_exact_html_bytes(tmp_path: Path) -> None:
    _, request = _workspace(tmp_path)
    app = create_html_editions_app(request)
    with TestClient(app) as client:
        build = client.post("/api/html-editions/builds", headers={"Idempotency-Key": "client-key"}, json={"project": "thesis", "document": "sample"})
        job_id = build.json()["job_id"]
        preview = client.post(f"/api/html-editions/builds/{job_id}/preview", json={"lifetime_seconds": 60})
        downloaded = client.get(f"/api/html-editions/builds/{job_id}/download")
        shown = client.get(f"/api/html-editions/previews/{preview.json()['token']}")
        result = (build.status_code, preview.status_code, downloaded.content == shown.content)
    assert result == (200, 200, True)
