"""MCP 鉴权模块：OAuth 2.1 授权服务器 + 静态 Token 鉴权 + 工具使用记录。

静态 Token 鉴权流程：
1. 客户端在 HTTP Header 中传入 Authorization: Bearer <token>
2. 服务端计算 SHA-256(token)，与 mcp_auth_tokens.token_hash 比对
3. 校验 token 状态（1=启用）和有效期
4. 更新 last_used_at，返回用户信息
5. 工具调用完成后记录到 mcp_tool_usage 表
"""

import hashlib
import json
import os
import secrets
import time
from typing import Any

from fastmcp.server.auth.auth import (
    AccessToken,
    AuthProvider,
    ClientRegistrationOptions,
    OAuthProvider as _OAuthProvider,
    TokenVerifier,
)
from mcp.server.auth.handlers.token import TokenHandler, TokenErrorResponse
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.routing import Route

# ========== 配置 ==========

_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "https://xhzjds.cnfic.com.cn")
_REQUIRED_SCOPES = ["mcp"]
_ACCESS_TOKEN_TTL = int(os.getenv("MCP_OAUTH_ACCESS_TTL", "3600"))  # 1 小时
_REFRESH_TOKEN_TTL = int(os.getenv("MCP_OAUTH_REFRESH_TTL", "2592000"))  # 30 天
_AUTH_CODE_TTL = 600  # 授权码 10 分钟有效


class MemoryOAuthProvider(_OAuthProvider):
    """基于内存存储的完整 OAuth 2.1 授权服务器实现。

    支持授权码流程（PKCE）和客户端凭证流程。
    客户端注册信息、授权码、Token 均存储在内存中。
    """

    def __init__(
        self,
        *,
        base_url: str,
        resource_base_url: str | None = None,
        issuer_url: str | None = None,
        service_documentation_url: str | None = None,
        client_registration_options: ClientRegistrationOptions | None = None,
        required_scopes: list[str] | None = None,
    ):
        super().__init__(
            base_url=base_url,
            resource_base_url=resource_base_url,
            issuer_url=issuer_url,
            service_documentation_url=service_documentation_url,
            client_registration_options=client_registration_options,
            required_scopes=required_scopes,
        )

        # 内存存储
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    # ----- 客户端管理 -----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    # ----- 授权码管理 -----

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """创建并存储授权码，返回授权码字符串。"""
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + _AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self._auth_codes[code] = auth_code
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, code: str
    ) -> AuthorizationCode | None:
        auth_code = self._auth_codes.get(code)
        if auth_code is None:
            return None
        if auth_code.expires_at < time.time():
            self._auth_codes.pop(code, None)
            return None
        if auth_code.client_id != client.client_id:
            return None
        return auth_code

    # ----- Token 管理 -----

    def _generate_token(self) -> str:
        return secrets.token_urlsafe(48)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """交换授权码，签发 access_token 和 refresh_token。"""
        # 消耗授权码（防重放）
        self._auth_codes.pop(authorization_code.code, None)
        return await self._issue_tokens(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """刷新 token，签发新的 access_token 和 refresh_token。"""
        # 废弃旧的 refresh_token
        self._refresh_tokens.pop(refresh_token.token, None)
        return await self._issue_tokens(
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
        )

    async def _issue_tokens(
        self, client_id: str, scopes: list[str]
    ) -> OAuthToken:
        """签发 access_token 和 refresh_token。"""
        now = int(time.time())

        # access_token
        access_token_str = self._generate_token()
        access_token = AccessToken(
            token=access_token_str,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + _ACCESS_TOKEN_TTL,
        )
        self._access_tokens[access_token_str] = access_token

        # refresh_token
        refresh_token_str = self._generate_token()
        refresh_token = RefreshToken(
            token=refresh_token_str,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + _REFRESH_TOKEN_TTL,
        )
        self._refresh_tokens[refresh_token_str] = refresh_token

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_TTL,
            refresh_token=refresh_token_str,
            scope=" ".join(scopes) if scopes else "",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self._access_tokens.get(token)
        if access_token is None:
            return None
        if access_token.expires_at is not None and access_token.expires_at < time.time():
            self._access_tokens.pop(token, None)
            return None
        return access_token

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, token: str
    ) -> RefreshToken | None:
        refresh_token = self._refresh_tokens.get(token)
        if refresh_token is None:
            return None
        if (
            refresh_token.expires_at is not None
            and refresh_token.expires_at < time.time()
        ):
            self._refresh_tokens.pop(token, None)
            return None
        if refresh_token.client_id != client.client_id:
            return None
        return refresh_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)

    # ----- 扩展：支持 client_credentials grant -----

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """覆写父类 get_routes，用支持 client_credentials 的自定义 TokenHandler 替换默认 handler。"""
        routes = super().get_routes(mcp_path)
        client_auth = ClientAuthenticator(self)
        for i, route in enumerate(routes):
            if getattr(route, "path", None) == "/token" and route.methods and "POST" in route.methods:
                handler = _ClientCredentialsTokenHandler(provider=self, client_authenticator=client_auth)
                routes[i] = Route(
                    path="/token",
                    endpoint=handler.handle,
                    methods=["POST", "OPTIONS"],
                )
                break
        return routes


class _ClientCredentialsTokenHandler(TokenHandler):
    """支持 authorization_code、refresh_token 和 client_credentials 三种 grant 的 Token Handler。"""

    async def handle(self, request):
        body = await request.form()
        grant_type = body.get("grant_type")

        if grant_type == "client_credentials":
            return await self._handle_client_credentials(request, body)

        # 其他 grant 类型委托给父类处理
        return await super().handle(request)

    async def _handle_client_credentials(self, request, body):
        client_id = body.get("client_id")
        client_secret = body.get("client_secret")
        scope = body.get("scope", "")

        if not client_id:
            return TokenErrorResponse("invalid_client", "Missing client_id")

        client = await self.provider.get_client(client_id)
        if client is None:
            return TokenErrorResponse("invalid_client", "Unknown client_id")

        if client.client_secret and client.client_secret != client_secret:
            return TokenErrorResponse("invalid_client", "Invalid client_secret")

        scopes = scope.split() if scope else client.scopes_supported or ["mcp"]

        if isinstance(self.provider, MemoryOAuthProvider):
            tokens = await self.provider._issue_tokens(
                client_id=client_id, scopes=scopes
            )
            from starlette.responses import JSONResponse
            return JSONResponse({
                "access_token": tokens.access_token,
                "token_type": "Bearer",
                "expires_in": tokens.expires_in,
                "scope": tokens.scope or " ".join(scopes),
            })
        return TokenErrorResponse("unsupported_grant_type", "client_credentials not supported")


def create_oauth_provider(
    service_key: str,
    gateway_url: str | None = None,
    enable_client_registration: bool = True,
    required_scopes: list[str] | None = None,
) -> MemoryOAuthProvider:
    """创建 OAuth 2.1 授权服务器 Provider。

    使用本地地址作为 base_url（OAuth 端点挂载在本地），
    issuer_url 使用网关地址（供客户端发现）。

    Args:
        service_key: 服务标识（finance/enterprise/person_insight/entity_resolve）。
        gateway_url: 公共网关 URL（默认从环境变量 MCP_GATEWAY_URL 读取）。
        enable_client_registration: 是否启用动态客户端注册。
        required_scopes: 必需的作用域列表。

    Returns:
        配置好的 MemoryOAuthProvider 实例。
    """
    if gateway_url is None:
        gateway_url = _GATEWAY_URL
    if required_scopes is None:
        required_scopes = _REQUIRED_SCOPES

    from common.api_client import BASE_URL as API_BASE_URL
    local_port = {
        "finance": 8907,
        "enterprise": 8908,
        "person_insight": 8909,
        "entity_resolve": 8910,
    }.get(service_key, 8907)
    local_url = f"http://127.0.0.1:{local_port}"

    registration_options = ClientRegistrationOptions(
        enabled=enable_client_registration,
        valid_scopes=required_scopes,
        default_scopes=required_scopes,
    )

    return MemoryOAuthProvider(
        base_url=local_url,
        issuer_url=gateway_url,
        required_scopes=required_scopes,
        client_registration_options=registration_options,
        service_documentation_url=f"{gateway_url}/cece-mcp-servers/{service_key}/docs",
    )


async def register_static_client(
    provider: MemoryOAuthProvider,
    client_id: str | None = None,
    client_secret: str | None = None,
    grant_types: list[str] | None = None,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """注册静态客户端（预置固定凭证，无需动态注册）。

    Args:
        provider: MemoryOAuthProvider 实例。
        client_id: 客户端 ID（None 则自动生成）。
        client_secret: 客户端密钥（None 则自动生成）。
        grant_types: 允许的授权类型（默认 authorization_code + refresh_token）。
        scopes: 允许的作用域。

    Returns:
        注册的客户端信息（含 client_id / client_secret）。
    """
    if client_id is None:
        client_id = f"mcp_{secrets.token_hex(8)}"
    if client_secret is None:
        client_secret = secrets.token_urlsafe(32)
    if grant_types is None:
        grant_types = ["authorization_code", "refresh_token"]
    if scopes is None:
        scopes = _REQUIRED_SCOPES

    client_info = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        grant_types=grant_types,
        response_types=["code"],
        scope=" ".join(scopes),
        token_endpoint_auth_method="client_secret_basic",
    )
    await provider.register_client(client_info)

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_types": grant_types,
        "scopes": scopes,
        "token_endpoint_auth_method": "client_secret_basic",
        "issuer": str(provider.issuer_url) if provider.issuer_url else "",
    }


# =============================================================================
# 静态 Token 鉴权（基于 mcp_auth_tokens 表）
# =============================================================================

import hashlib
from datetime import datetime

from fastmcp.exceptions import ToolError

_AUTH_ERROR = ToolError("未授权：缺少或无效的 Authorization Token。")
_HEADER_PREFIX = "Bearer "


class AuthInfo:
    """鉴权成功后传递给调用记录的用户信息。"""

    __slots__ = ("token_id", "user_id", "user_name")

    def __init__(self, token_id: int, user_id: int, user_name: str):
        self.token_id = token_id
        self.user_id = user_id
        self.user_name = user_name


def _parse_auth_header(auth_header: str) -> str:
    """从 Authorization header 中提取 Bearer token。"""
    if not auth_header or not auth_header.startswith(_HEADER_PREFIX):
        raise _AUTH_ERROR
    return auth_header[len(_HEADER_PREFIX):].strip()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def validate_static_token(auth_header: str) -> AuthInfo:
    """验证静态 Bearer Token，返回鉴权信息。

    Args:
        auth_header: HTTP Authorization header 原始值。

    Returns:
        AuthInfo 包含 token_id / user_id / user_name。

    Raises:
        ToolError: Token 无效、过期或已被禁用。
    """
    token = _parse_auth_header(auth_header)
    token_hash = _hash_token(token)

    from common.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT id, user_id, user_name, status, expires_at
                   FROM a_sh_mgr.mcp_auth_tokens
                   WHERE token_hash = %s""",
                (token_hash,),
            )
            row = await cur.fetchone()

    if row is None:
        raise ToolError("未授权：Token 不存在或已失效。")

    token_id, user_id, user_name, status, expires_at = row

    if status != 1:
        raise ToolError("未授权：Token 已被禁用。")

    if expires_at is not None and expires_at < datetime.now():
        raise ToolError("未授权：Token 已过期。")

    # 异步更新 last_used_at
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE a_sh_mgr.mcp_auth_tokens SET last_used_at = NOW() WHERE id = %s",
                (token_id,),
            )

    return AuthInfo(token_id=token_id, user_id=user_id, user_name=user_name)


async def log_tool_usage(
    auth_info: AuthInfo | None,
    tool_name: str,
    arguments: dict | None,
    result: str,
    error_message: str | None = None,
    duration_ms: int | None = None,
    client_ip: str | None = None,
) -> None:
    """记录工具调用日志到 mcp_tool_usage 表。

    使用 MCP 标准 OAuth 2.1 鉴权时，auth_info 为 None，
    token_id/user_id 用 0 填充，user_name 用空字符串。

    Args:
        auth_info: 鉴权信息（可选，None 时使用默认值）。
        tool_name: 被调用的 MCP 工具名。
        arguments: 调用参数（注意脱敏）。
        result: 调用结果（success / error）。
        error_message: 失败时的错误信息。
        duration_ms: 工具执行耗时（毫秒）。
        client_ip: 调用来源 IP。
    """
    from common.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO a_sh_mgr.mcp_tool_usage
                   (token_id, user_id, user_name, tool_name, arguments, result, error_message, duration_ms, client_ip)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    auth_info.token_id if auth_info else 0,
                    auth_info.user_id if auth_info else 0,
                    auth_info.user_name if auth_info else "",
                    tool_name,
                    _sanitize_args(arguments),
                    result,
                    error_message,
                    duration_ms,
                    client_ip,
                ),
            )


def _sanitize_args(args: dict | None) -> str | None:
    """脱敏：仅记录参数 key，不记录敏感值。"""
    if not args:
        return None
    return str({k: "***" if _is_sensitive(k) else v for k, v in args.items()})


_SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "key", "credit_code"}


def _is_sensitive(key: str) -> bool:
    return any(s in key.lower() for s in _SENSITIVE_KEYS)