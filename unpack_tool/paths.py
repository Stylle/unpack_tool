import os
import sys
from dataclasses import dataclass
from pathlib import Path


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppPaths:
    base: Path
    links: Path
    torrents: Path
    database: Path

    @classmethod
    def create(cls, base: str | os.PathLike[str] | None = None) -> "AppPaths":
        root = Path(base).resolve() if base else application_dir()
        paths = cls(root, root / "links", root / "torrents", root / "app_data.db")
        paths.links.mkdir(parents=True, exist_ok=True)
        paths.torrents.mkdir(parents=True, exist_ok=True)
        return paths

