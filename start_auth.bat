@echo off
set MCP_AUTH_ENABLED=true
start /B python servers\finance_server.py
start /B python servers\enterprise_server.py
start /B python servers\person_insight_server.py
start /B python servers\entity_resolve_server.py
echo All 4 MCP services started with MCP_AUTH_ENABLED=true