#!/bin/bash
# 一键停止所有 MCP 服务（Linux 版）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "正在停止所有 MCP 服务..."

for pid_file in logs/*.pid; do
    if [ -f "$pid_file" ]; then
        pid="$(cat "$pid_file" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
        rm -f "$pid_file"
    fi
done

# 兜底：按进程名清理残留进程
pkill -f "servers/finance_server.py" 2>/dev/null
pkill -f "servers/enterprise_server.py" 2>/dev/null
pkill -f "servers/person_insight_server.py" 2>/dev/null
pkill -f "servers/entity_resolve_server.py" 2>/dev/null

sleep 2
echo "所有服务已停止。"