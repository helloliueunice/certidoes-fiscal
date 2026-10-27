"""Middlewares ASGI de segurança: limite de corpo da requisição e cabeçalhos HTTP.

Puro ASGI (sem BaseHTTPMiddleware) para funcionar com uploads em streaming.
"""
from __future__ import annotations

import json
from typing import Callable

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://cdngovbr-ds.estaleiro.serpro.gov.br https://cdnjs.cloudflare.com; "
    "font-src 'self' data: https://cdngovbr-ds.estaleiro.serpro.gov.br https://cdnjs.cloudflare.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self' mailto:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

CABECALHOS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
]


class CabecalhosSeguranca:
    """Acrescenta CSP, nosniff, Referrer-Policy, X-Frame-Options e Permissions-Policy."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def enviar(msg):
            if msg["type"] == "http.response.start":
                existentes = {k.lower() for k, _ in msg.get("headers", [])}
                msg = dict(msg)
                msg["headers"] = list(msg.get("headers", [])) + [
                    (k, v) for k, v in CABECALHOS if k not in existentes]
            await send(msg)

        await self.app(scope, receive, enviar)


class _CorpoGrande(Exception):
    pass


class LimiteCorpo:
    """Recusa com 413 requisições com corpo maior que o limite da rota.

    Confere o Content-Length declarado e, além disso, conta os bytes recebidos em streaming
    (cobre requisições sem Content-Length ou com valor falso). Se o limite estourar no meio da
    leitura, a resposta da aplicação é descartada e substituída pelo 413.
    """

    METODOS = {"POST", "PUT", "PATCH"}

    def __init__(self, app, limite_para: Callable[[str], int],
                 pagina_html: Callable[[int], str]):
        self.app = app
        self.limite_para = limite_para
        self.pagina_html = pagina_html

    async def _recusar(self, scope, send, limite: int) -> None:
        if scope["path"].startswith("/api/"):
            corpo = json.dumps({"ok": False, "mensagem": "Envio grande demais.",
                                "limite_bytes": limite}, ensure_ascii=False).encode()
            tipo = b"application/json"
        else:
            corpo = self.pagina_html(limite).encode()
            tipo = b"text/html; charset=utf-8"
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", tipo), (b"content-length", str(len(corpo)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": corpo})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in self.METODOS:
            return await self.app(scope, receive, send)
        limite = self.limite_para(scope["path"])
        declarado = None
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-length":
                try:
                    declarado = int(v)
                except ValueError:
                    declarado = limite + 1
        if declarado is not None and declarado > limite:
            return await self._recusar(scope, send, limite)

        recebidos = 0
        estourou = False
        iniciou = False

        async def receber():
            nonlocal recebidos, estourou
            if estourou:
                raise _CorpoGrande()
            msg = await receive()
            if msg["type"] == "http.request":
                recebidos += len(msg.get("body", b""))
                if recebidos > limite:
                    estourou = True
                    raise _CorpoGrande()
            return msg

        async def enviar(msg):
            nonlocal iniciou
            if estourou:
                return          # descarta a resposta da aplicação (ex.: 400 de corpo inválido)
            if msg["type"] == "http.response.start":
                iniciou = True
            await send(msg)

        try:
            await self.app(scope, receber, enviar)
        except _CorpoGrande:
            pass
        except Exception:
            if not estourou:
                raise
        if estourou and not iniciou:
            await self._recusar(scope, send, limite)

