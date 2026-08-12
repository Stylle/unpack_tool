import pytest

from unpack_tool.links import LinkFormatError, join_download_path, parse_link_lines


def test_parses_plain_and_sub_path_formats():
    items = parse_link_lines(
        [
            "{website}/download.php?id=1&passkey={passkey}",
            "电影合集/第一部|{website}/dl/2/{passkey}",
        ],
        "https://tracker.example/",
        "secret",
    )

    assert [item.url for item in items] == [
        "https://tracker.example/download.php?id=1&passkey=secret",
        "https://tracker.example/dl/2/secret",
    ]
    assert items[1].sub_path == "电影合集/第一部"


def test_parses_legacy_literal_placeholders():
    [item] = parse_link_lines(
        ["https://website/download.php?id=1&passkey=yourpasskey"],
        "https://tracker.example",
        "secret",
    )
    assert item.url == "https://tracker.example/download.php?id=1&passkey=secret"


def test_join_download_path_handles_remote_windows_and_posix_paths():
    assert join_download_path(r"D:\Media", "合集/第一部") == r"D:\Media\合集\第一部"
    assert join_download_path("/data/media", "合集/第一部") == "/data/media/合集/第一部"


@pytest.mark.parametrize("sub_path", ["../outside", r"C:\outside", "/outside"])
def test_rejects_unsafe_sub_paths(sub_path):
    with pytest.raises(LinkFormatError):
        join_download_path("/data", sub_path)

