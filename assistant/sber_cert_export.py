"""Copy a sandbox client certificate out of the disposable browser container."""

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


DEFAULT_CERT_PATH = Path.home() / ".local/share/sber-assistant/secrets/sandbox-client.p12"


def export_sber_p12(filename: str, destination: Path) -> Path:
    """Export one downloaded .p12, without exposing the host to the browser."""
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".p12"):
        raise ValueError("Expected a .p12 filename from the browser Downloads directory")

    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(destination.parent.stat().st_mode) != 0o700:
        raise PermissionError("Certificate destination directory must have mode 0700")

    with tempfile.TemporaryDirectory(prefix="sber-cert-", dir=destination.parent) as staging:
        subprocess.run(
            ["docker", "cp", f"yandex-isolated:/home/browser/Downloads/{filename}", staging],
            check=True,
        )
        source = Path(staging, filename)
        if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
            raise ValueError("Downloaded certificate is missing, empty, or a symlink")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as target, source.open("rb") as origin:
                shutil.copyfileobj(origin, target)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a Sber sandbox .p12 from the isolated browser")
    parser.add_argument("filename", help="Name of the .p12 file in browser Downloads")
    parser.add_argument("--output", type=Path, default=DEFAULT_CERT_PATH)
    args = parser.parse_args()
    print(export_sber_p12(args.filename, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
