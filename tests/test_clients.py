import json

from unpack_tool.clients import QBittorrentClient, TransmissionClient


class FakeResponse:
    def __init__(self, status=200, text="", headers=None, data=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self._data = data

    def json(self):
        return self._data if self._data is not None else json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeQBSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/auth/login"):
            return FakeResponse(text="Ok.")
        if url.endswith("/app/version"):
            return FakeResponse(text="5.1.4")
        if url.endswith("/app/webapiVersion"):
            return FakeResponse(text="2.11.4")
        if url.endswith("/torrents/add"):
            return FakeResponse(text="Ok.")
        raise AssertionError(url)


def test_qb_uses_same_cookie_login_for_v4_and_v5_api(tmp_path):
    torrent = tmp_path / "sample.torrent"
    torrent.write_bytes(b"d4:infode")
    session = FakeQBSession()
    client = QBittorrentClient("127.0.0.1", "8080", "admin", "password", session=session)

    ok, message = client.test_connection()
    assert ok is True
    assert "5.1.4" in message
    ok, _ = client.add_torrent_file(str(torrent), r"D:\Media", paused=True)
    assert ok is True
    add_call = next(call for call in session.calls if call[1].endswith("/torrents/add"))
    assert add_call[2]["data"]["savepath"] == r"D:\Media"
    assert add_call[2]["data"]["paused"] == "true"
    assert add_call[2]["data"]["stopped"] == "true"
    assert not any("api_key" in str(call) or "X-API-Key" in str(call) for call in session.calls)


class FakeTransmissionSession:
    def __init__(self):
        self.auth = None
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        if len(self.calls) == 1:
            return FakeResponse(409, headers={"X-Transmission-Session-Id": "session-1"})
        if json["method"] == "session-get":
            return FakeResponse(data={"result": "success", "arguments": {"version": "4.0.6"}})
        if json["method"] == "torrent-add":
            return FakeResponse(data={"result": "success", "arguments": {"torrent-added": {"id": 7}}})
        raise AssertionError(json)


def test_transmission_retries_409_and_pushes_download_dir(tmp_path):
    torrent = tmp_path / "sample.torrent"
    torrent.write_bytes(b"torrent")
    session = FakeTransmissionSession()
    client = TransmissionClient("127.0.0.1", "9091", session=session)

    assert client.test_connection()[0] is True
    ok, identifier = client.add_torrent_file(str(torrent), "/media/movies", paused=True)
    assert ok is True
    assert identifier == "7"
    add_call = next(call for call in session.calls if call[1]["method"] == "torrent-add")
    assert add_call[1]["arguments"]["download-dir"] == "/media/movies"
    assert add_call[1]["arguments"]["paused"] is True
