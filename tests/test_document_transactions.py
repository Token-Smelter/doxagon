import json

import pytest

from doxagon.wal import WriteAheadLog, WriterFence, RecoveryUnresolved, read_authority_generation


@pytest.fixture
def transaction(tmp_path):
    fence = WriterFence(tmp_path)
    fence.acquire()
    journal = WriteAheadLog(tmp_path, fence)
    journal.initialize()
    targets = {tmp_path / 'page.html': b'<p>New edition</p>', tmp_path / 'notes.json': b'{"edition":"new"}'}
    for path in targets:
        path.write_bytes(b'old')
    yield journal, targets
    fence.release()


@pytest.mark.parametrize('interruption', [0, 1, 2])
def test_multi_file_recovery_at_every_promotion_boundary(transaction, monkeypatch, interruption):
    journal, targets = transaction
    install = journal._install
    count = 0
    def interrupted(item):
        nonlocal count
        if count == interruption:
            raise RuntimeError('power loss')
        install(item)
        count += 1
        if count == 2 and interruption == 2:
            raise RuntimeError('power loss')
    monkeypatch.setattr(journal, '_install', interrupted)
    with pytest.raises(RuntimeError):
        journal.commit_replace_many(targets)
    assert read_authority_generation(journal._vault_root)[0] == 1
    monkeypatch.setattr(journal, '_install', install)
    assert journal.recover()
    assert {path: path.read_bytes() for path in targets} == targets
    assert read_authority_generation(journal._vault_root) == (2, None)
    assert journal.recover() is None


def test_corrupted_remaining_postimage_keeps_recovery_unresolved(transaction, monkeypatch):
    journal, targets = transaction
    install = journal._install
    def interrupted(item):
        install(item)
        raise RuntimeError('power loss')
    monkeypatch.setattr(journal, '_install', interrupted)
    with pytest.raises(RuntimeError):
        journal.commit_replace_many(targets)
    remaining = next(journal._vault_root.rglob('*.postimage'))
    remaining.write_bytes(b'corrupt')
    monkeypatch.setattr(journal, '_install', install)
    with pytest.raises(RecoveryUnresolved, match='hash disagrees'):
        journal.recover()
    with pytest.raises(RecoveryUnresolved):
        journal.commit_replace_many(targets)
    assert read_authority_generation(journal._vault_root)[0] % 2


def test_crash_before_activation_preserves_prior_authority(transaction, monkeypatch):
    journal, targets = transaction
    prepare = journal._prepare_many
    def interrupted(*args):
        prepare(*args)
        raise RuntimeError('power loss')
    monkeypatch.setattr(journal, '_prepare_many', interrupted)
    with pytest.raises(RuntimeError):
        journal.commit_replace_many(targets)
    assert journal.recover() is None
    assert all(path.read_bytes() == b'old' for path in targets)


def test_single_file_records_remain_recoverable(transaction, monkeypatch):
    journal, targets = transaction
    install = journal._install
    monkeypatch.setattr(journal, '_install', lambda _: (_ for _ in ()).throw(RuntimeError('power loss')))
    path = next(iter(targets))
    with pytest.raises(RuntimeError):
        journal.commit_replace(path, b'compatible')
    record = json.loads(next(journal._wal_root.glob('*.json')).read_text())
    assert record['format'] == 1
    monkeypatch.setattr(journal, '_install', install)
    journal.recover()
    assert path.read_bytes() == b'compatible'


def test_multi_target_escape_is_refused_before_staging(transaction):
    journal, _ = transaction
    with pytest.raises(RecoveryUnresolved):
        journal.commit_replace_many({journal._vault_root.parent / 'outside': b'no'})
    assert read_authority_generation(journal._vault_root) == (0, None)


def test_replacement_preserves_existing_read_permissions(transaction):
    journal, targets = transaction
    for path in targets:
        path.chmod(0o640)
    created = journal._vault_root / 'new-definition.md'
    journal.commit_replace_many({**targets, created: b'New definition'})
    assert all(path.stat().st_mode & 0o777 == 0o640 for path in targets)
    assert created.stat().st_mode & 0o777 == 0o644
