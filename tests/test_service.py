import threading

from unpack_tool.models import STATUS_DOWNLOADED, STATUS_PUSHED, TorrentItem
from unpack_tool.service import TorrentService
from unpack_tool.storage import StateStore


class RecordingClient:
    def __init__(self):
        self.calls = []

    def add_torrent_file(self, torrent_path, save_path, paused=False):
        self.calls.append((torrent_path, save_path, paused))
        return True, "ok"


def test_push_uses_sub_path_and_keeps_torrent_by_default(tmp_path):
    torrent_dir = tmp_path / "torrents"
    torrent_dir.mkdir()
    torrent = torrent_dir / "sample.torrent"
    torrent.write_bytes(b"torrent")
    store = StateStore(tmp_path / "state.db")
    item = TorrentItem("https://example.test/1", str(torrent), STATUS_DOWNLOADED, "合集/第一部")
    store.replace_items([item])
    service = TorrentService(store, torrent_dir)
    client = RecordingClient()

    result = service.push_downloaded(
        [item], client, "/media", False, False, threading.Event(),
        lambda *_: None, lambda: None,
    )
    assert result == (1, 0)
    assert client.calls[0][1] == "/media/合集/第一部"
    assert torrent.exists()
    assert item.status == STATUS_PUSHED


def test_push_adds_torrent_in_paused_state_when_enabled(tmp_path):
    torrent_dir = tmp_path / "torrents"
    torrent_dir.mkdir()
    torrent = torrent_dir / "sample.torrent"
    torrent.write_bytes(b"torrent")
    store = StateStore(tmp_path / "state.db")
    item = TorrentItem("https://example.test/1", str(torrent), STATUS_DOWNLOADED)
    store.replace_items([item])
    service = TorrentService(store, torrent_dir)
    client = RecordingClient()
    result = service.push_downloaded(
        [item], client, "/media", False, True, threading.Event(),
        lambda *_: None, lambda: None,
    )
    assert result == (1, 0)
    assert len(client.calls) == 1
    assert client.calls[0][2] is True
