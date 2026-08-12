from pathlib import Path
import hashlib

from unpack_tool.models import STATUS_DOWNLOADED, STATUS_PENDING, TorrentItem
from unpack_tool.storage import StateStore


def test_config_and_items_survive_restart(tmp_path):
    database = tmp_path / "state.db"
    torrent = tmp_path / "cached.torrent"
    torrent.write_bytes(b"torrent")
    store = StateStore(database)
    store.save_config({"min_delay": "2.5", "max_delay": "9", "delete_after_push": "0"})
    item = TorrentItem("https://example.test/1", str(torrent), STATUS_DOWNLOADED, "电影/第一部")
    store.replace_items([item])

    reopened = StateStore(database)
    [restored] = reopened.load_items()
    assert reopened.get_config("min_delay") == "2.5"
    assert reopened.get_config("max_delay") == "9"
    assert reopened.get_config("delete_after_push") == "0"
    assert restored.status == STATUS_DOWNLOADED
    assert restored.sub_path == "电影/第一部"


def test_reconcile_recovers_untracked_torrent_after_interruption(tmp_path):
    torrent_dir = tmp_path / "torrents"
    torrent_dir.mkdir()
    orphan = torrent_dir / "orphan.torrent"
    orphan.write_bytes(b"torrent")
    store = StateStore(tmp_path / "state.db")

    [restored] = store.reconcile(torrent_dir)
    assert restored.filepath == str(orphan.resolve())
    assert restored.status == STATUS_DOWNLOADED


def test_reconcile_marks_missing_download_as_pending(tmp_path):
    store = StateStore(tmp_path / "state.db")
    item = TorrentItem("https://example.test/1", str(tmp_path / "missing.torrent"), STATUS_DOWNLOADED)
    store.replace_items([item])

    [restored] = store.reconcile(tmp_path)
    assert restored.status == STATUS_PENDING
    assert restored.filepath == ""


def test_reconcile_rebinds_deterministic_file_and_preserves_sub_path(tmp_path):
    torrent_dir = tmp_path / "torrents"
    torrent_dir.mkdir()
    url = "https://example.test/download/1"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    torrent = torrent_dir / f"torrent_{digest}.torrent"
    torrent.write_bytes(b"torrent")
    store = StateStore(tmp_path / "state.db")
    store.replace_items([TorrentItem(url, sub_path="合集/第一部")])

    [restored] = store.reconcile(torrent_dir)
    assert restored.filepath == str(torrent.resolve())
    assert restored.status == STATUS_DOWNLOADED
    assert restored.sub_path == "合集/第一部"


def test_reconcile_maps_legacy_files_to_pending_items_in_order(tmp_path):
    torrent_dir = tmp_path / "torrents"
    torrent_dir.mkdir()
    first = torrent_dir / "torr_100_1000.torrent"
    second = torrent_dir / "torr_101_1001.torrent"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    store = StateStore(tmp_path / "state.db")
    store.replace_items(
        [
            TorrentItem("https://example.test/1", sub_path="第一部"),
            TorrentItem("https://example.test/2", sub_path="第二部"),
        ]
    )

    restored = store.reconcile(torrent_dir)
    assert [Path(item.filepath).name for item in restored] == [first.name, second.name]
    assert [item.sub_path for item in restored] == ["第一部", "第二部"]
