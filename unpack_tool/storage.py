import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import STATUS_DOWNLOADED, STATUS_PENDING, TorrentItem


class StateStore:
    def __init__(self, database: str | Path):
        self.database = str(database)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS torrent_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    filepath TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '待下载',
                    sub_path TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(torrent_items)")
            }
            migrations = {
                "sub_path": "TEXT NOT NULL DEFAULT ''",
                "error": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE torrent_items ADD COLUMN {name} {definition}"
                    )

    def get_config(self, key: str, default: str = "") -> str:
        with self._session() as connection:
            row = connection.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def save_config(self, values: dict[str, str]) -> None:
        with self._session() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                [(key, str(value)) for key, value in values.items()],
            )

    def load_items(self) -> list[TorrentItem]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT id, url, filepath, status, sub_path, error "
                "FROM torrent_items ORDER BY id"
            ).fetchall()
        return [
            TorrentItem(
                item_id=row["id"],
                url=row["url"],
                filepath=row["filepath"] or "",
                status=row["status"] or STATUS_PENDING,
                sub_path=row["sub_path"] or "",
                error=row["error"] or "",
            )
            for row in rows
        ]

    def replace_items(self, items: list[TorrentItem]) -> None:
        with self._session() as connection:
            connection.execute("DELETE FROM torrent_items")
            for item in items:
                cursor = connection.execute(
                    "INSERT INTO torrent_items (url, filepath, status, sub_path, error) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (item.url, item.filepath, item.status, item.sub_path, item.error),
                )
                item.item_id = cursor.lastrowid

    def save_item(self, item: TorrentItem) -> None:
        with self._session() as connection:
            if item.item_id is None:
                cursor = connection.execute(
                    "INSERT INTO torrent_items (url, filepath, status, sub_path, error) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (item.url, item.filepath, item.status, item.sub_path, item.error),
                )
                item.item_id = cursor.lastrowid
            else:
                connection.execute(
                    "UPDATE torrent_items SET url=?, filepath=?, status=?, sub_path=?, "
                    "error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        item.url,
                        item.filepath,
                        item.status,
                        item.sub_path,
                        item.error,
                        item.item_id,
                    ),
                )

    def reconcile(self, torrent_dir: str | Path) -> list[TorrentItem]:
        directory = Path(torrent_dir)
        items = self.load_items()
        known: set[Path] = set()
        for item in items:
            if not item.filepath:
                digest = hashlib.sha1(item.url.encode("utf-8")).hexdigest()[:12]
                recovered = directory / f"torrent_{digest}.torrent"
                if recovered.exists():
                    item.filepath = str(recovered.resolve())
                    item.status = STATUS_DOWNLOADED
                    item.error = ""
                    self.save_item(item)
                else:
                    continue
            path = Path(item.filepath)
            known.add(path.resolve())
            if path.exists() and item.status == STATUS_PENDING:
                item.status = STATUS_DOWNLOADED
                self.save_item(item)
            elif not path.exists() and item.status == STATUS_DOWNLOADED:
                item.filepath = ""
                item.status = STATUS_PENDING
                self.save_item(item)

        orphaned = [
            path
            for path in directory.glob("*.torrent")
            if path.resolve() not in known
        ]
        legacy_files = sorted(
            (path for path in orphaned if re.fullmatch(r"torr_\d+_\d+\.torrent", path.name)),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        recoverable_items = [
            item
            for item in items
            if not item.filepath and item.status in {STATUS_PENDING, "失败"}
        ]
        for item, path in zip(recoverable_items, legacy_files):
            item.filepath = str(path.resolve())
            item.status = STATUS_DOWNLOADED
            item.error = ""
            self.save_item(item)
            known.add(path.resolve())

        for path in sorted(directory.glob("*.torrent")):
            if path.resolve() in known:
                continue
            items.append(
                TorrentItem(
                    url=f"local://{path.name}",
                    filepath=str(path.resolve()),
                    status=STATUS_DOWNLOADED,
                )
            )
            self.save_item(items[-1])
        return self.load_items()

    def clear(self) -> None:
        with self._session() as connection:
            connection.execute("DELETE FROM config")
            connection.execute("DELETE FROM torrent_items")
