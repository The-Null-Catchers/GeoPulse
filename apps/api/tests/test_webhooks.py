import asyncio
import socket
import ssl
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractResolver
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
import pytest
from geopulse import webhooks as hooks
from geopulse.security import opaque


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        hooks,
        "settings",
        replace(
            hooks.settings,
            webhook_encryption_key=Fernet.generate_key().decode(),
            webhook_allowed_hosts=("receiver.example", "receiver.test", "127.0.0.1", "8.8.8.8"),
        ),
    )


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.0.1",
        "172.16.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - rejection input, never a bind address
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
    ],
)
def test_private_special_and_translated_addresses_are_blocked(ip):
    assert not hooks.public_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://receiver.example/hook",
        "https://receiver.example:8443/hook",
        "https://user:password@receiver.example/hook",
        "https://receiver.example/#fragment",
        "https://receiver.example.evil/hook",
        "https://127.0.0.1/hook",
        "https://receiver.example\\@evil.test",
        "https://receiver.example/\nhook",
    ],
)
def test_destination_validation(configured, url):
    with pytest.raises(HTTPException):
        hooks.validate_url(url)


def test_public_destination_and_encrypted_signing_key(configured):
    assert hooks.validate_url("https://receiver.example/hook") == "https://receiver.example/hook"
    assert hooks.public_ip("8.8.8.8")
    secret = opaque("gph")
    encrypted = hooks.cipher().encrypt(secret.encode())
    assert secret.encode() not in encrypted
    assert hooks.cipher().decrypt(encrypted).decode() == secret


def test_resolver_pins_one_public_lookup_and_rejects_mixed_dns(configured, monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        calls = []

        async def public(host, port, **kwargs):
            calls.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

        monkeypatch.setattr(loop, "getaddrinfo", public)
        resolved = await hooks.PublicResolver().resolve("receiver.example", 443)
        assert calls == ["receiver.example"]
        assert resolved[0]["host"] == "8.8.8.8" and resolved[0]["flags"] == socket.AI_NUMERICHOST

        async def mixed(host, port, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            ]

        monkeypatch.setattr(loop, "getaddrinfo", mixed)
        with pytest.raises(OSError):
            await hooks.PublicResolver().resolve("receiver.example", 443)

    asyncio.run(run())


def test_signature_binds_time_delivery_and_body(configured):
    secret = opaque("gph")
    delivery = str(uuid4())
    body = hooks.body_bytes({"type": "alert.created", "data": {"name": "تنبيه"}})
    signed = hooks.signature(secret, "123456", delivery, body)
    assert signed != hooks.signature(secret, "123457", delivery, body)
    assert signed != hooks.signature(secret, "123456", str(uuid4()), body)
    assert signed != hooks.signature(secret, "123456", delivery, body + b" ")


def tls_contexts(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "receiver.test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("receiver.test")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / "receiver.pem"
    key_file = tmp_path / "receiver.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_file, key_file)
    client = ssl.create_default_context(cafile=str(cert_file))
    return server, client


async def receiver(monkeypatch, tmp_path, handler):
    server_ssl, client_ssl = tls_contexts(tmp_path)
    app = web.Application()
    app.router.add_post("/hook", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_ssl)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    # Test-only network mapping to a local TLS peer; production uses PublicResolver.
    class TestResolver(AbstractResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": site._server.sockets[0].getsockname()[1],
                    "family": socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]

        async def close(self):
            pass

    assert port > 0
    monkeypatch.setattr(
        hooks,
        "make_connector",
        lambda: aiohttp.TCPConnector(resolver=TestResolver(), ssl=client_ssl, use_dns_cache=False),
    )
    return runner


def test_real_https_transport_signature_and_no_redirect(configured, monkeypatch, tmp_path):
    async def run():
        import hashlib
        import hmac

        secret = opaque("gph")
        delivery = str(uuid4())
        received = []

        async def handle(request):
            raw = await request.read()
            signed = (
                request.headers["X-GeoPulse-Timestamp"].encode()
                + b"."
                + request.headers["X-GeoPulse-Delivery"].encode()
                + b"."
                + raw
            )
            expected = "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
            assert hmac.compare_digest(expected, request.headers["X-GeoPulse-Signature"])
            assert request.headers["X-GeoPulse-Delivery"] == delivery
            received.append(raw)
            return web.Response(status=307, headers={"Location": "https://127.0.0.1/private"})

        runner = await receiver(monkeypatch, tmp_path, handle)
        try:
            response = await hooks.send_webhook(
                "https://receiver.test/hook", secret, delivery, {"type": "alert.created"}
            )
            assert response.http_status == 307 and not response.retryable
            assert len(received) == 1
        finally:
            await runner.cleanup()

    asyncio.run(run())
