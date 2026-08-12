import hashlib
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from .clients import QBittorrentClient, TransmissionClient, write_test_torrent
from .links import join_download_path
from .models import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_PENDING, STATUS_PUSHED, TorrentItem
from .storage import StateStore


LogCallback = Callable[[str, bool], None]
ProgressCallback = Callable[[], None]


class TorrentService:
    def __init__(self, store: StateStore, torrent_dir: str | Path):
        self.store = store
        self.torrent_dir = Path(torrent_dir)
        self.torrent_dir.mkdir(parents=True, exist_ok=True)

    def download_pending(
        self,
        items: list[TorrentItem],
        min_delay: float,
        max_delay: float,
        pause_event: threading.Event,
        stop_event: threading.Event,
        log: LogCallback,
        progress: ProgressCallback,
    ) -> tuple[int, int]:
        pending = [
            item
            for item in items
            if item.status == STATUS_PENDING
            or (item.status == STATUS_FAILED and not item.filepath)
        ]
        success = failure = 0
        for index, item in enumerate(pending):
            if stop_event.is_set():
                break
            while pause_event.is_set() and not stop_event.wait(0.25):
                pass
            if stop_event.is_set():
                break
            digest = hashlib.sha1(item.url.encode("utf-8")).hexdigest()[:12]
            target = self.torrent_dir / f"torrent_{digest}.torrent"
            temporary = target.with_suffix(".torrent.part")
            try:
                response = requests.get(item.url, timeout=30)
                response.raise_for_status()
                content = response.content
                if not content.startswith(b"d") or b"4:info" not in content:
                    raise ValueError("服务器响应不是有效的种子文件")
                temporary.write_bytes(content)
                os.replace(temporary, target)
                item.filepath = str(target.resolve())
                item.status = STATUS_DOWNLOADED
                item.error = ""
                success += 1
                log(f"已下载: {target.name}", False)
            except Exception as exc:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                item.status = STATUS_FAILED
                item.error = str(exc)
                failure += 1
                log(f"下载失败: {exc}", True)
            self.store.save_item(item)
            progress()
            if index < len(pending) - 1 and not stop_event.is_set():
                delay = random.uniform(min_delay, max_delay)
                log(f"随机等待 {delay:.1f} 秒", False)
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline and not stop_event.wait(0.2):
                    while pause_event.is_set() and not stop_event.wait(0.25):
                        pass
        return success, failure

    def push_downloaded(
        self,
        items: list[TorrentItem],
        client,
        base_save_path: str,
        delete_after_push: bool,
        pause_event: threading.Event,
        stop_event: threading.Event,
        log: LogCallback,
        progress: ProgressCallback,
    ) -> tuple[int, int]:
        candidates = [
            item
            for item in items
            if item.filepath
            and Path(item.filepath).exists()
            and item.status != STATUS_PUSHED
        ]
        success = failure = 0
        for item in candidates:
            if stop_event.is_set():
                break
            while pause_event.is_set() and not stop_event.wait(0.25):
                pass
            save_path = join_download_path(base_save_path, item.sub_path)
            ok, message = client.add_torrent_file(item.filepath, save_path)
            if ok:
                item.status = STATUS_PUSHED
                item.error = ""
                success += 1
                log(f"已推送: {Path(item.filepath).name} -> {save_path}", False)
                if delete_after_push:
                    try:
                        Path(item.filepath).unlink()
                        item.filepath = ""
                    except OSError as exc:
                        log(f"推送成功，但删除本地种子失败: {exc}", True)
            else:
                item.status = STATUS_FAILED
                item.error = message
                failure += 1
                log(f"推送失败 [{Path(item.filepath).name}]: {message}", True)
            self.store.save_item(item)
            progress()
        return success, failure

    def test_push(self, client, save_path: str) -> tuple[bool, str]:
        test_path = self.torrent_dir / ".unpack_tool_push_test.torrent"
        info_hash = write_test_torrent(test_path)
        try:
            ok, identifier = client.add_torrent_file(str(test_path), save_path, paused=True)
            if not ok:
                return False, identifier
            remove_id = info_hash if isinstance(client, QBittorrentClient) else identifier
            location_ok, actual_path = client.torrent_location(remove_id)
            clean_ok, clean_message = client.remove_torrent(remove_id)
            if not clean_ok:
                return True, f"推送成功，但自动清理失败: {clean_message}"
            if not location_ok:
                return False, f"推送成功，但无法验证路径: {actual_path}"
            expected = save_path.replace("\\", "/").rstrip("/").casefold()
            actual = actual_path.replace("\\", "/").rstrip("/").casefold()
            if expected != actual:
                return False, f"路径不一致：期望 {save_path}，下载器实际使用 {actual_path}"
            return True, f"推送路径有效: {actual_path}；测试种子已自动清理"
        finally:
            try:
                test_path.unlink()
            except FileNotFoundError:
                pass
