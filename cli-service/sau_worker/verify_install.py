"""Byte-compare an activated desktop image with the retained content-addressed archive."""

import hashlib
import zipfile
from pathlib import Path


class IncompleteImage(ValueError):
    pass


def verify_committed(root, digest):
    program = root / "program"
    file = root / ".versions/download/package.zip"
    with file.open("rb") as saved:
        if hashlib.file_digest(saved, "sha256").hexdigest() != digest:
            raise IncompleteImage("Interrupted package download")
        saved.seek(0)
        with zipfile.ZipFile(saved) as archive:
            for member in archive.infolist():
                path = program / member.filename
                if not path.resolve().is_relative_to(program.resolve()) or path.is_symlink():
                    raise IncompleteImage("Interrupted program installation")
                with archive.open(member) as expected, path.open("rb") as actual:
                    while chunk := expected.read(512 * 1024):
                        if actual.read(len(chunk)) != chunk:
                            raise IncompleteImage("Interrupted program installation")
                    if actual.read(1):
                        raise IncompleteImage("Interrupted program installation")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    try:
        verify_committed(root, (root / ".versions/switch").read_text().strip())
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc))
