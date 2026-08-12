# Entity MCP

面向企业、集团、产业、园区、人物、区域查询的 MCP 服务集合。六个服务均使用 Streamable HTTP，可独立部署，也可由 ADK Agent 通过 MCP URL 连接。

## 安装与配置

```bash
pip install -r requirements.txt
```

在 `.env` 配置网关和 Milvus 所需凭据。该文件包含密钥，不应提交到 Git。

## 启动

```bash
python servers/company_server.py
python servers/group_server.py
python servers/industry_server.py
python servers/park_server.py
python servers/person_server.py
python servers/region_server.py
```

| 服务 | 地址 |
| --- | --- |
| company-mcp | `http://127.0.0.1:8901/mcp/company/stream` |
| group-mcp | `http://127.0.0.1:8902/mcp/group/stream` |
| industry-mcp | `http://127.0.0.1:8903/mcp/industry/stream` |
| park-mcp | `http://127.0.0.1:8904/mcp/park/stream` |
| person-mcp | `http://127.0.0.1:8905/mcp/person/stream` |
| region-mcp | `http://127.0.0.1:8906/mcp/region/stream` |

详细说明见 [docs](docs/)。迁移或继续开发前，请先阅读 [HANDOFF.md](HANDOFF.md)。
