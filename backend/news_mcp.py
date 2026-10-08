"""Official SDK Streamable HTTP with service auth and per-job trusted context."""
import contextvars
import secrets
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .bailian import AIError

_context = contextvars.ContextVar('news_mcp_context', default='')


class AuthenticatedMCP:
    def __init__(self, app, get_service):
        self.app, self.get_service = app, get_service

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        service = self.get_service()
        headers = dict(scope.get('headers', []))
        expected = ('Bearer ' + service.settings.mcp_key).encode() if service else b''
        if (not service or not service.settings.mcp_enabled or service.tool_problem
                or len(service.settings.mcp_key) < 32):
            return await JSONResponse({'error': 'disabled'}, status_code=503)(scope, receive, send)
        if not secrets.compare_digest(headers.get(b'authorization', b''), expected):
            return await JSONResponse({'error': 'unauthorized'}, status_code=401)(scope, receive, send)
        token = headers.get(b'x-news-context', b'')
        if len(token) > 4000:
            return await JSONResponse({'error': 'invalid_context'}, status_code=403)(scope, receive, send)
        try:
            current = _context.set(token.decode('ascii'))
        except UnicodeDecodeError:
            return await JSONResponse({'error': 'invalid_context'}, status_code=403)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            _context.reset(current)


def build(get_service):
    # Reverse proxy handles the public Host. Auth is required; no browser-origin access.
    sdk = FastMCP('news-reader', stateless_http=True, json_response=True,
                  max_request_body_size=16000, log_level='CRITICAL',
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @sdk.tool()
    async def read_news(article_id: int) -> dict[str, Any]:
        """Read the current registered article. Scope comes from trusted request headers, never model input."""
        try:
            if article_id < 1:
                raise AIError('tool_scope', 403)
            return await get_service().read_tool(_context.get(), article_id)
        except AIError as error:
            return {'read_status': 'blocked', 'error': error.code, 'blocks': []}

    return sdk, AuthenticatedMCP(sdk.streamable_http_app(), get_service)
