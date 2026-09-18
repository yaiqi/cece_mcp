@echo off
echo === With valid Authorization token ===
curl.exe -s -X POST http://127.0.0.1:8907/cece-mcp-servers/PEVC/stream -H "Authorization: Bearer 894c98bebec8a0c03cba633a66d32d276e9c490a410dbcfd3cba832d175c2867" -H "Content-Type: application/json" -H "mcp-session-id: test" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}" --connect-timeout 5
echo.
echo.
echo === Without Authorization token ===
curl.exe -s -X POST http://127.0.0.1:8907/cece-mcp-servers/PEVC/stream -H "Content-Type: application/json" -H "mcp-session-id: test2" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}" --connect-timeout 5
echo.
echo.
echo === With invalid Authorization token ===
curl.exe -s -X POST http://127.0.0.1:8907/cece-mcp-servers/PEVC/stream -H "Authorization: Bearer invalidtoken123" -H "Content-Type: application/json" -H "mcp-session-id: test3" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}" --connect-timeout 5