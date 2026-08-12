import ntpath
import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

from .models import TorrentItem


class LinkFormatError(ValueError):
    pass


def _render_url(template: str, website: str, passkey: str) -> str:
    site = website.rstrip("/")
    rendered = template.replace("{website}", site).replace("{passkey}", passkey)
    rendered = rendered.replace("https://website", site).replace("http://website", site)
    rendered = rendered.replace("yourpasskey", passkey)
    parsed = urlparse(rendered)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LinkFormatError(f"无效链接: {rendered}")
    return rendered


def parse_link_lines(lines: list[str], website: str, passkey: str) -> list[TorrentItem]:
    items: list[TorrentItem] = []
    seen: set[str] = set()
    errors: list[str] = []
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sub_path, separator, template = line.partition("|")
        if not separator:
            template, sub_path = sub_path, ""
        try:
            url = _render_url(template.strip(), website, passkey)
            validate_sub_path(sub_path.strip())
        except LinkFormatError as exc:
            errors.append(f"第 {line_number} 行: {exc}")
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append(TorrentItem(url=url, sub_path=sub_path.strip()))
    if not items and errors:
        raise LinkFormatError("\n".join(errors[:5]))
    return items


def parse_link_file(path: str | Path, website: str, passkey: str) -> list[TorrentItem]:
    with open(path, "r", encoding="utf-8-sig") as stream:
        return parse_link_lines(stream.readlines(), website, passkey)


def validate_sub_path(sub_path: str) -> None:
    if not sub_path:
        return
    windows = PureWindowsPath(sub_path)
    posix = PurePosixPath(sub_path)
    if windows.is_absolute() or posix.is_absolute() or windows.drive:
        raise LinkFormatError("指定路径必须是相对路径")
    if ".." in windows.parts or ".." in posix.parts:
        raise LinkFormatError("指定路径不能包含 ..")


def join_download_path(base_path: str, sub_path: str) -> str:
    base = base_path.strip()
    if not base:
        raise LinkFormatError("做种路径不能为空")
    validate_sub_path(sub_path)
    if not sub_path:
        return base
    if "\\" in base or (len(base) >= 2 and base[1] == ":"):
        return ntpath.normpath(ntpath.join(base, sub_path.replace("/", "\\")))
    return posixpath.normpath(posixpath.join(base, sub_path.replace("\\", "/")))

