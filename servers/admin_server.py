"""MCP 管理后台：用户注册、Token 创建与查询。

独立运行（端口 8911），不依赖 MCP 鉴权，用于管理用户和访问凭证。
"""

import hashlib
import secrets
from datetime import datetime, timedelta

import aiomysql
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

DB_CONFIG = {
    "host": "192.168.202.147",
    "port": 3306,
    "user": "a_sh_hydc_liyaqi",
    "password": "DDDKhsfU@20260605",
    "db": "a_sh_ods",
    "charset": "utf8mb4",
    "autocommit": True,
}

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=3)
    return _pool


async def register(request: Request):
    try:
        body = await request.json()
        for field in ("mobile", "name", "account"):
            if not body.get(field):
                return JSONResponse({"error": f"缺少必填字段: {field}"}, status_code=400)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM a_sh_mgr.mcp_user WHERE mobile = %s", (body["mobile"],))
                if await cur.fetchone():
                    return JSONResponse({"error": "该手机号已注册"}, status_code=409)

                await cur.execute(
                    """INSERT INTO a_sh_mgr.mcp_user
                       (name, account, mobile, email, company, department, region_code, company_tel,
                        position, company_addr, cru, account_type, status, apply_date, contract_code,
                        deadline, user_group, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        body.get("name", ""), body.get("account", ""), body["mobile"],
                        body.get("email", ""), body.get("company", ""), body.get("department", ""),
                        body.get("region_code", ""), body.get("company_tel", ""),
                        body.get("position", ""), body.get("company_addr", ""),
                        body.get("cru", ""), body.get("account_type", ""),
                        body.get("status", 1), body.get("apply_date"),
                        body.get("contract_code", ""), body.get("deadline"),
                        body.get("user_group", ""), body.get("created_by", ""),
                    ),
                )
                user_id = cur.lastrowid

        return JSONResponse({"message": "注册成功", "user_id": user_id}, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_token(request: Request):
    try:
        body = await request.json()
        mobile = body.get("mobile", "")
        token_name = body.get("token_name", "")
        if not mobile:
            return JSONResponse({"error": "缺少手机号"}, status_code=400)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM a_sh_mgr.mcp_user WHERE mobile = %s", (mobile,))
                user = await cur.fetchone()
                if not user:
                    return JSONResponse({"error": "未找到该手机号的用户"}, status_code=404)

                user_id, user_name = user
                token = secrets.token_hex(32)
                token_hash = hashlib.sha256(token.encode()).hexdigest()

                await cur.execute(
                    """INSERT INTO a_sh_mgr.mcp_auth_tokens
                       (user_id, user_name, token_hash, token_name, status, expires_at, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (user_id, user_name, token_hash, token_name or "管理后台创建", 1,
                     datetime.now() + timedelta(days=365), datetime.now()),
                )
                token_id = cur.lastrowid

        return JSONResponse({
            "token_id": token_id, "user_id": user_id, "user_name": user_name,
            "token": token, "authorization": f"Bearer {token}",
            "expires_at": (datetime.now() + timedelta(days=365)).isoformat(),
            "注意": "Token 明文仅此一次返回，请妥善保存",
        }, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def query_tokens(request: Request):
    try:
        body = await request.json()
        mobile = body.get("mobile", "")
        if not mobile:
            return JSONResponse({"error": "缺少手机号"}, status_code=400)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM a_sh_mgr.mcp_user WHERE mobile = %s", (mobile,))
                user = await cur.fetchone()
                if not user:
                    return JSONResponse({"error": "未找到该手机号的用户"}, status_code=404)

                user_id, user_name = user
                await cur.execute(
                    """SELECT id, token_hash, token_name, status, expires_at, created_at, last_used_at
                       FROM a_sh_mgr.mcp_auth_tokens WHERE user_id = %s ORDER BY created_at DESC""",
                    (user_id,),
                )
                rows = await cur.fetchall()

        tokens = []
        for r in rows:
            tokens.append({
                "token_id": r[0],
                "token_name": r[2] or "",
                "status": "启用" if r[3] == 1 else "禁用",
                "expires_at": r[4].isoformat() if r[4] else "永不过期",
                "created_at": r[5].isoformat() if r[5] else "",
                "last_used_at": r[6].isoformat() if r[6] else "从未使用",
            })

        return JSONResponse({
            "user_id": user_id, "user_name": user_name, "mobile": mobile, "tokens": tokens,
            "提示": "Token 哈希值不可逆，无法还原明文。需要新 Token 请使用 /create-token 接口创建。",
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


app = Starlette(
    debug=False,
    routes=[
        Route("/register", register, methods=["POST"]),
        Route("/create-token", create_token, methods=["POST"]),
        Route("/query-tokens", query_tokens, methods=["POST"]),
    ],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8911)