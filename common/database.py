"""MySQL 异步数据库连接池，用于 MCP 鉴权与使用记录。

在服务启动时自动初始化连接池（lazy），服务停止时通过 close_pool() 关闭。
"""

import os

import aiomysql

_pool: aiomysql.Pool | None = None

_DB_CONFIG = {
    "host": os.getenv("MCP_DB_HOST", "192.168.202.147"),
    "port": int(os.getenv("MCP_DB_PORT", "3306")),
    "user": os.getenv("MCP_DB_USER", "a_sh_hydc_liyaqi"),
    "password": os.getenv("MCP_DB_PASSWORD", "DDDKhsfU@20260605"),
    "db": os.getenv("MCP_DB_NAME", "a_sh_ods"),
    "charset": "utf8mb4",
    "autocommit": True,
}


async def get_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(**_DB_CONFIG, minsize=1, maxsize=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None