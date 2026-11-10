"""Read-only connection probe for the official Sber API MCP sandbox.

This module never selects the production host and never calls a tool. It only
performs the MCP handshake and lists tools using a sandbox mTLS identity.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx2
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


SANDBOX_MCP_URLS = {
    "payment": "https://fintech-test.sberbank.ru:9443/fintech/api/business-payments/mcp",
    "client_info": "https://fintech-test.sberbank.ru:9443/fintech/api/client-info/mcp",
    "statement": "https://fintech-test.sberbank.ru:9443/fintech/api/statement/mcp",
    "encashment": "https://fintech-test.sberbank.ru:9443/fintech/api/encashment/mcp",
    "placement": "https://fintech-test.sberbank.ru:9443/fintech/api/placement/mcp",
}


@dataclass(frozen=True)
class SandboxCredentials:
    """The Sber API identity, distinct from GigaChat API credentials."""

    access_token: str
    p12_path: Path
    p12_password: str
    ca_bundle: Path | None = None

    @classmethod
    def from_env(cls) -> "SandboxCredentials":
        names = ("SBER_API_ACCESS_TOKEN", "SBER_API_P12_PATH", "SBER_API_P12_PASSWORD")
        missing = [name for name in names if not os.getenv(name)]
        if missing:
            raise ValueError("Не настроены параметры песочницы: " + ", ".join(missing))
        p12_path = Path(os.environ["SBER_API_P12_PATH"]).expanduser()
        ca_value = os.getenv("SBER_API_CA_BUNDLE")
        ca_bundle = Path(ca_value).expanduser() if ca_value else None
        if not p12_path.is_file():
            raise ValueError("Файл клиентского .p12 сертификата не найден")
        if ca_bundle is not None and not ca_bundle.is_file():
            raise ValueError("Файл доверенного CA bundle не найден")
        return cls(os.environ["SBER_API_ACCESS_TOKEN"], p12_path,
                   os.environ["SBER_API_P12_PASSWORD"], ca_bundle)

    @classmethod
    def from_prompt(cls) -> "SandboxCredentials":
        """Read a temporary identity from the terminal without saving secrets."""
        p12_path = Path(input("Путь к тестовому .p12: ").strip()).expanduser()
        p12_password = getpass.getpass("Пароль .p12: ")
        access_token = getpass.getpass("Тестовый access token: ")
        ca_value = input("Путь к CA bundle (Enter — системное доверие): ").strip()
        ca_bundle = Path(ca_value).expanduser() if ca_value else None
        if not p12_path.is_file():
            raise ValueError("Файл клиентского .p12 сертификата не найден")
        if not p12_password or not access_token:
            raise ValueError("Пароль .p12 и access token обязательны")
        if ca_bundle is not None and not ca_bundle.is_file():
            raise ValueError("Файл доверенного CA bundle не найден")
        return cls(access_token, p12_path, p12_password, ca_bundle)


def _ssl_context(credentials: SandboxCredentials) -> ssl.SSLContext:
    """Load PKCS#12 into an SSL context without retaining key files on disk."""
    try:
        key, certificate, chain = pkcs12.load_key_and_certificates(
            credentials.p12_path.read_bytes(), credentials.p12_password.encode()
        )
    except (OSError, ValueError) as exc:
        raise ValueError("Не удалось открыть клиентский .p12 сертификат") from exc
    if key is None or certificate is None:
        raise ValueError("В .p12 отсутствует клиентский ключ или сертификат")
    context = ssl.create_default_context(
        cafile=str(credentials.ca_bundle) if credentials.ca_bundle else None
    )
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    cert_pem += b"".join(item.public_bytes(serialization.Encoding.PEM) for item in chain or [])
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with tempfile.TemporaryDirectory(prefix="sber-mtls-") as directory:
        cert_path = Path(directory) / "client.crt"
        key_path = Path(directory) / "client.key"
        cert_path.write_bytes(cert_pem)
        key_path.write_bytes(key_pem)
        os.chmod(cert_path, 0o600)
        os.chmod(key_path, 0o600)
        context.load_cert_chain(str(cert_path), str(key_path))
    return context


async def list_sandbox_tools(service: str, credentials: SandboxCredentials) -> list[str]:
    """Probe one allowlisted sandbox MCP server; return only tool names."""
    if service not in SANDBOX_MCP_URLS:
        raise ValueError("Неизвестный сервис песочницы")
    context = _ssl_context(credentials)
    timeout = httpx2.Timeout(15.0, read=30.0)
    async with httpx2.AsyncClient(
        verify=context,
        headers={"Authorization": f"Bearer {credentials.access_token}"},
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        return await _list_tools_with_client(SANDBOX_MCP_URLS[service], http_client)


async def _list_tools_with_client(url: str, http_client: httpx2.AsyncClient) -> list[str]:
    async with streamable_http_client(
        url, http_client=http_client, terminate_on_close=False,
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream,
                                 read_timeout_seconds=30.0) as session:
            await session.initialize()
            result = await session.list_tools()
            return sorted(tool.name for tool in result.tools)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Sber API MCP sandbox probe")
    parser.add_argument("--service", choices=SANDBOX_MCP_URLS,
                        default="client_info")
    parser.add_argument("--interactive", action="store_true",
                        help="Запросить сертификат и секреты в терминале без .env")
    args = parser.parse_args()
    try:
        credentials = (SandboxCredentials.from_prompt() if args.interactive
                       else SandboxCredentials.from_env())
        tools = asyncio.run(list_sandbox_tools(args.service, credentials))
    except Exception as exc:
        # Never print an exception from a transport that may include headers.
        print(json.dumps({"status": "failed", "service": args.service,
                          "reason": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "connected", "service": args.service,
                      "tools": tools}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
