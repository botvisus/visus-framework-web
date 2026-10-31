"""A download is complete only when the browser's partial file is gone.

Firefox creates the FINAL name as an empty file next to ``<name>.part`` and fills
it when the download ends. Treating that empty placeholder as the finished file
handed back a 0-byte download (CI: ``assert '' == 'hello download'``). These tests
replay Firefox's exact sequence on a real directory.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate
from visus.web.cli.session_server import SessionHandler


def _firefox_downloads(folder: Path, name: str, body: str, *, after_s: float) -> threading.Thread:
    """Placeholder + .part now; content in place and .part removed *after_s* later."""
    (folder / name).write_bytes(b"")
    (folder / f"{name}.part").write_text(body[:3], encoding="utf-8")

    def finish() -> None:
        time.sleep(after_s)
        (folder / name).write_text(body, encoding="utf-8")
        (folder / f"{name}.part").unlink()

    thread = threading.Thread(target=finish)
    thread.start()
    return thread


def test_wait_for_download_ignores_firefox_empty_placeholder(tmp_path: Path) -> None:
    page = SimpleNamespace(_download_dir=str(tmp_path))
    thread = _firefox_downloads(tmp_path, "download.txt", "hello download", after_s=0.5)
    try:
        path, name = SeleniumPageDelegate.wait_for_download(page, [], timeout_ms=5000)  # type: ignore[arg-type]
        # read at once, as a caller would: the writer thread may still be running
        body = Path(path).read_text(encoding="utf-8")
    finally:
        thread.join()
    assert name == "download.txt"
    assert body == "hello download"


def test_session_downloads_skip_a_file_still_being_written(tmp_path: Path) -> None:
    (tmp_path / "done.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "busy.txt").write_bytes(b"")
    (tmp_path / "busy.txt.part").write_bytes(b"he")
    handler = SimpleNamespace(
        page=lambda: SimpleNamespace(_delegate=SimpleNamespace(_download_dir=str(tmp_path))),
        _PARTIAL_DOWNLOAD=SessionHandler._PARTIAL_DOWNLOAD,
    )
    names = [f["name"] for f in SessionHandler._completed_downloads(handler)]  # type: ignore[arg-type]
    assert names == ["done.txt"]
