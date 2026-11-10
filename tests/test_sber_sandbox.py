"""The remote connector must fail closed without a Sber API identity."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import pytest
import httpx2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from assistant.sber_sandbox import (
    SANDBOX_MCP_URLS,
    SandboxCredentials,
    _list_tools_with_client,
    _ssl_context,
    list_sandbox_tools,
    main,
)


def test_missing_identity_fails_before_network(monkeypatch) -> None:
    for name in ("SBER_API_ACCESS_TOKEN", "SBER_API_P12_PATH", "SBER_API_P12_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="SBER_API_ACCESS_TOKEN"):
        SandboxCredentials.from_env()


def test_interactive_identity_reads_secrets_without_environment(monkeypatch, tmp_path) -> None:
    p12 = tmp_path / "client.p12"
    p12.write_bytes(b"not-a-real-certificate")
    answers = iter((str(p12), ""))
    secrets = iter(("p12-password", "access-token"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(secrets))
    credentials = SandboxCredentials.from_prompt()
    assert credentials == SandboxCredentials("access-token", p12, "p12-password")


def test_interactive_cli_does_not_print_secrets(monkeypatch, tmp_path, capsys) -> None:
    p12 = tmp_path / "client.p12"
    p12.write_bytes(b"not-a-real-certificate")
    answers = iter((str(p12), ""))
    secrets = iter(("p12-password", "access-token"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(secrets))
    monkeypatch.setattr(sys, "argv", ["sber_sandbox", "--interactive"])

    async def fake_list(_service, credentials):
        assert credentials.access_token == "access-token"
        return ["accounts.get_list"]

    monkeypatch.setattr("assistant.sber_sandbox.list_sandbox_tools", fake_list)
    assert main() == 0
    output = capsys.readouterr().out
    assert '"status": "connected"' in output
    assert "access-token" not in output
    assert "p12-password" not in output


def test_urls_are_only_official_sandbox_hosts() -> None:
    assert len(SANDBOX_MCP_URLS) == 5
    assert all(url.startswith("https://fintech-test.sberbank.ru:9443/fintech/api/")
               and url.endswith("/mcp") for url in SANDBOX_MCP_URLS.values())


def test_pkcs12_is_loaded_as_mtls_identity(tmp_path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sandbox-test")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    password = "test-only-password"
    p12 = tmp_path / "client.p12"
    p12.write_bytes(pkcs12.serialize_key_and_certificates(
        b"test", key, cert, None,
        serialization.BestAvailableEncryption(password.encode()),
    ))
    context = _ssl_context(SandboxCredentials("test-token", p12, password))
    assert context.verify_mode.name == "CERT_REQUIRED"
    with pytest.raises(ValueError, match="Не удалось открыть"):
        _ssl_context(SandboxCredentials("test-token", p12, "wrong-password"))


def test_unknown_service_is_rejected_before_certificate_read(tmp_path) -> None:
    credentials = SandboxCredentials("test", tmp_path / "missing.p12", "password")
    with pytest.raises(ValueError, match="Неизвестный сервис"):
        asyncio.run(list_sandbox_tools("production", credentials))


@pytest.mark.asyncio
async def test_streamable_http_handshake_lists_tools() -> None:
    server = MCPServer(name="local-test")

    @server.tool(name="accounts.get_list")
    def accounts_get_list() -> dict:
        return {"accounts": []}

    app = server.streamable_http_app(
        json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1"],
        ),
    )
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            names = await _list_tools_with_client("http://127.0.0.1/mcp", client)
    assert names == ["accounts.get_list"]
