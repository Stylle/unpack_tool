import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = 15


class DownloaderError(RuntimeError):
    pass


def normalize_base_url(host: str, port: str) -> str:
    value = host.strip().rstrip("/")
    if not value:
        raise DownloaderError("地址不能为空")
    if "://" not in value:
        value = "http://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloaderError("下载器地址格式无效")
    if parsed.port or parsed.path not in {"", "/"} or not port.strip():
        return value
    return f"{value}:{port.strip()}"


class QBittorrentClient:
    """qBittorrent Web API v2 client compatible with qBittorrent 4.x and 5.x."""

    def __init__(
        self,
        host: str,
        port: str,
        username: str = "",
        password: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ):
        self.base_url = normalize_base_url(host, port)
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self.session = session or requests.Session()
        self.authenticated = False
        self.session.headers.update(
            {"Origin": self.base_url, "Referer": self.base_url + "/"}
        )

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        try:
            return self.session.request(method, self.base_url + endpoint, **kwargs)
        except requests.ConnectionError as exc:
            raise DownloaderError(f"无法连接到 {self.base_url}") from exc
        except requests.Timeout as exc:
            raise DownloaderError(f"连接超时: {self.base_url}") from exc
        except requests.RequestException as exc:
            raise DownloaderError(str(exc)) from exc

    def _login(self) -> None:
        if not self.username:
            self.authenticated = True
            return
        response = self._request(
            "POST",
            "/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        if response.status_code != 200 or response.text.strip().lower() not in {"ok.", "ok"}:
            detail = response.text.strip() or f"HTTP {response.status_code}"
            raise DownloaderError(f"qBittorrent 登录失败: {detail}")
        self.authenticated = True

    def _ensure_authenticated(self) -> str:
        if not self.authenticated:
            self._login()
        response = self._request("GET", "/api/v2/app/version")
        if response.status_code in {401, 403} and self.username:
            self.authenticated = False
            self._login()
            response = self._request("GET", "/api/v2/app/version")
        if response.status_code != 200:
            detail = response.text.strip() or f"HTTP {response.status_code}"
            raise DownloaderError(f"qBittorrent API 拒绝访问: {detail}")
        return response.text.strip()

    def test_connection(self) -> tuple[bool, str]:
        try:
            version = self._ensure_authenticated()
            api_response = self._request("GET", "/api/v2/app/webapiVersion")
            api_version = api_response.text.strip() if api_response.status_code == 200 else "?"
            return True, f"qBittorrent {version} (Web API {api_version}) 连接成功"
        except DownloaderError as exc:
            return False, str(exc)

    def add_torrent_file(
        self, torrent_path: str, save_path: str, paused: bool = False
    ) -> tuple[bool, str]:
        try:
            self._ensure_authenticated()
            with open(torrent_path, "rb") as stream:
                files = {
                    "torrents": (
                        os.path.basename(torrent_path),
                        stream,
                        "application/x-bittorrent",
                    )
                }
                data = {
                    "savepath": save_path,
                    "autoTMM": "false",
                    "paused": "true" if paused else "false",
                    "stopped": "true" if paused else "false",
                }
                response = self._request(
                    "POST", "/api/v2/torrents/add", files=files, data=data
                )
            body = response.text.strip()
            if response.status_code == 200 and body.lower() in {"", "ok", "ok."}:
                return True, "推送成功"
            return False, f"qBittorrent 返回 {body or '空响应'} (HTTP {response.status_code})"
        except (OSError, DownloaderError) as exc:
            return False, str(exc)

    def remove_torrent(self, torrent_hash: str) -> tuple[bool, str]:
        try:
            response = self._request(
                "POST",
                "/api/v2/torrents/delete",
                data={"hashes": torrent_hash, "deleteFiles": "false"},
            )
            if response.status_code == 200:
                return True, "测试种子已清理"
            return False, f"清理失败 HTTP {response.status_code}"
        except DownloaderError as exc:
            return False, str(exc)

    def torrent_location(self, torrent_hash: str) -> tuple[bool, str]:
        try:
            response = self._request(
                "GET", "/api/v2/torrents/properties", params={"hash": torrent_hash}
            )
            if response.status_code != 200:
                return False, f"读取测试种子路径失败 HTTP {response.status_code}"
            return True, str(response.json().get("save_path", ""))
        except (ValueError, DownloaderError) as exc:
            return False, str(exc)


class TransmissionClient:
    def __init__(
        self,
        host: str,
        port: str,
        username: str = "",
        password: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ):
        self.base_url = normalize_base_url(host, port)
        suffix = "" if self.base_url.endswith("/transmission/rpc") else "/transmission/rpc"
        self.rpc_url = self.base_url + suffix
        self.timeout = timeout
        self.session = session or requests.Session()
        if username.strip():
            self.session.auth = (username.strip(), password)
        self.session_id = ""

    def _post(self, payload: dict) -> requests.Response:
        headers = {"X-Transmission-Session-Id": self.session_id} if self.session_id else {}
        try:
            response = self.session.post(
                self.rpc_url, json=payload, headers=headers, timeout=self.timeout
            )
            if response.status_code == 409:
                self.session_id = response.headers.get("X-Transmission-Session-Id", "")
                if not self.session_id:
                    raise DownloaderError("Transmission 未返回 Session ID")
                response = self.session.post(
                    self.rpc_url,
                    json=payload,
                    headers={"X-Transmission-Session-Id": self.session_id},
                    timeout=self.timeout,
                )
            if response.status_code == 401:
                raise DownloaderError("Transmission 用户名或密码错误")
            response.raise_for_status()
            return response
        except requests.ConnectionError as exc:
            raise DownloaderError(f"无法连接到 {self.rpc_url}") from exc
        except requests.Timeout as exc:
            raise DownloaderError(f"连接超时: {self.rpc_url}") from exc
        except requests.RequestException as exc:
            raise DownloaderError(str(exc)) from exc

    def _rpc(self, method: str, arguments: dict | None = None) -> dict:
        response = self._post({"method": method, "arguments": arguments or {}})
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloaderError("Transmission 返回了无效 JSON") from exc
        if data.get("result") != "success":
            raise DownloaderError(str(data.get("result", "未知错误")))
        return data.get("arguments", {})

    def test_connection(self) -> tuple[bool, str]:
        try:
            details = self._rpc("session-get")
            return True, f"Transmission {details.get('version', '?')} 连接成功"
        except DownloaderError as exc:
            return False, str(exc)

    def add_torrent_file(
        self, torrent_path: str, save_path: str, paused: bool = False
    ) -> tuple[bool, str]:
        try:
            metainfo = base64.b64encode(Path(torrent_path).read_bytes()).decode("ascii")
            result = self._rpc(
                "torrent-add",
                {
                    "metainfo": metainfo,
                    "download-dir": save_path,
                    "paused": paused,
                },
            )
            added = result.get("torrent-added") or result.get("torrent-duplicate") or {}
            torrent_id = added.get("id")
            if torrent_id is None:
                return False, "Transmission 未返回种子 ID"
            return True, str(torrent_id)
        except (OSError, DownloaderError) as exc:
            return False, str(exc)

    def remove_torrent(self, torrent_id: str) -> tuple[bool, str]:
        try:
            self._rpc(
                "torrent-remove",
                {"ids": [int(torrent_id)], "delete-local-data": False},
            )
            return True, "测试种子已清理"
        except (ValueError, DownloaderError) as exc:
            return False, str(exc)

    def torrent_location(self, torrent_id: str) -> tuple[bool, str]:
        try:
            details = self._rpc(
                "torrent-get", {"ids": [int(torrent_id)], "fields": ["downloadDir"]}
            )
            torrents = details.get("torrents", [])
            if not torrents:
                return False, "Transmission 中未找到测试种子"
            return True, str(torrents[0].get("downloadDir", ""))
        except (ValueError, DownloaderError) as exc:
            return False, str(exc)


def write_test_torrent(path: str | Path) -> str:
    name = b"unpack_tool_push_test.txt"
    piece_hash = hashlib.sha1(b"x").digest()
    info = (
        b"d6:lengthi1e4:name"
        + str(len(name)).encode("ascii")
        + b":"
        + name
        + b"12:piece lengthi16384e6:pieces20:"
        + piece_hash
        + b"e"
    )
    torrent = b"d8:announce27:http://127.0.0.1:9/announce4:info" + info + b"e"
    Path(path).write_bytes(torrent)
    return hashlib.sha1(info).hexdigest()
