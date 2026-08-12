from dataclasses import dataclass


STATUS_PENDING = "待下载"
STATUS_DOWNLOADED = "已下载"
STATUS_PUSHED = "已推送"
STATUS_FAILED = "失败"


@dataclass
class TorrentItem:
    url: str
    filepath: str = ""
    status: str = STATUS_PENDING
    sub_path: str = ""
    error: str = ""
    item_id: int | None = None

