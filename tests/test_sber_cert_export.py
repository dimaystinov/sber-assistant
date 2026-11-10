"""Certificate export must keep the browser container isolated from host files."""

import stat
from pathlib import Path

import pytest

from assistant.sber_cert_export import export_sber_p12


def test_export_sber_p12_creates_private_host_copy(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "secrets" / "sandbox-client.p12"
    commands = []

    def fake_run(command, check):
        commands.append(command)
        Path(command[-1], "sandbox.p12").write_bytes(b"sample-p12")

    monkeypatch.setattr("assistant.sber_cert_export.subprocess.run", fake_run)
    result = export_sber_p12("sandbox.p12", destination)

    assert result == destination
    assert destination.read_bytes() == b"sample-p12"
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert commands[0][:3] == ["docker", "cp", "yandex-isolated:/home/browser/Downloads/sandbox.p12"]


@pytest.mark.parametrize("filename", ["../secret.p12", "/tmp/secret.p12", "not-p12.txt"])
def test_export_rejects_non_basename_or_wrong_extension(filename, tmp_path) -> None:
    with pytest.raises(ValueError):
        export_sber_p12(filename, tmp_path / "client.p12")


def test_export_refuses_to_overwrite_existing_identity(tmp_path) -> None:
    destination = tmp_path / "client.p12"
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        export_sber_p12("sandbox.p12", destination)
    assert destination.read_bytes() == b"existing"
