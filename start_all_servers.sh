#!/bin/bash
# 一键启动所有 MCP 服务（Linux 版）
# 网关鉴权凭据优先读取系统环境变量（export ENTITY_API_AUTHORIZATION=... / ENTITY_API_XSEC=...），
# 未设置时自动加载项目根目录 .env 文件（由 api_client.py 内置解析，无需 python-dotenv）。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON="${PYTHON:-/data/python3.10/bin/python3.10}"

mkdir -p logs

echo "正在启动 MCP 服务..."

nohup "$PYTHON" servers/finance_server.py > logs/finance_server.log 2>&1 &
echo $! > logs/finance_server.pid
sleep 2

nohup "$PYTHON" servers/enterprise_server.py > logs/enterprise_server.log 2>&1 &
echo $! > logs/enterprise_server.pid
sleep 2

nohup "$PYTHON" servers/person_insight_server.py > logs/person_insight_server.log 2>&1 &
echo $! > logs/person_insight_server.pid
sleep 2

nohup "$PYTHON" servers/entity_resolve_server.py > logs/entity_resolve_server.log 2>&1 &
echo $! > logs/entity_resolve_server.pid
sleep 3

echo ""
echo "所有服务已启动："
echo "  finance-mcp         :8907 /cece-mcp-servers/PEVC/stream"
echo "  enterprise-mcp      :8908 /cece-mcp-servers/enterprise/stream"
echo "  person-insight-mcp  :8909 /cece-mcp-servers/person/stream"
echo "  entity-resolve-mcp  :8910 /cece-mcp-servers/NER/stream"
echo ""
echo "查看日志： tail -f logs/<服务名>.log"
echo "停止所有服务： bash stop_all_servers.sh"