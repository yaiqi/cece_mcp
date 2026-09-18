# Entity MCP（行业洞察）

按《（毅达客户）行业洞察 MCP 清单》需求文档实现的企业信息查询 MCP 服务集合。基于 [FastMCP](https://github.com/jlowin/fastmcp) 框架（v4），使用 Streamable HTTP 传输，可独立部署，也可由 MCP 客户端（如 ADK Agent）通过 URL 连接。

## 架构概览

```
entity_MCP/
├── common/                    # 共享模块
│   ├── server_factory.py     # FastMCP 工厂、工具注册、错误拦截
│   ├── api_client.py         # 上游网关 HTTP 客户端（连接池 + 信封解包）
│   ├── business_protocol.py  # MCP 错误规范契约（ToolError vs 正常返回）
│   ├── output_shaping.py     # 出参整形管线（信封清理、ID 剔除、键翻译、字段筛选）
│   ├── field_mapper.py       # 英中字段名自动翻译（JSON 配置 + 自动词典）
│   ├── address.py            # 中文地区名 → 行政区划代码
│   └── auth.py               # OAuth 2.1 授权服务器
├── entities/                  # 业务逻辑（4 个实体模块）
│   ├── finance.py            # 9 个创投融资工具
│   ├── enterprise.py         # 17 个企业工具
│   ├── person_insight.py     # 8 个人物洞察工具
│   └── entity_resolve.py     # 4 个主体识别工具
├── servers/                   # 服务入口
│   ├── finance_server.py           # :8907
│   ├── enterprise_server.py        # :8908
│   ├── person_insight_server.py    # :8909
│   └── entity_resolve_server.py    # :8910
├── models/                    # Pydantic 数据模型
├── data/                      # 字段映射配置、区域代码
├── tests/                     # 单元测试
├── mcp.conf                   # Nginx 反向代理配置
├── start_all_servers.sh       # 一键启动脚本
└── stop_all_servers.sh        # 一键停止脚本
```

所有服务共享：
- 同一上游网关（`xhzjds.cnfic.com.cn`），统一鉴权（JWT + x-Sec）
- 同一 HTTP 连接池（`httpx.AsyncClient`）
- 同一出参整形管线（自动清除信封层、剔除 ID 字段、英中键翻译、按工具功能筛选字段）
- 同一 MCP 错误规范

## 服务列表

### 1. finance-mcp（创投融资 Sever）
- **端口**: 8907
- **路径**: `/cece-mcp-servers/PEVC/stream`
- **工具数**: 9

| 工具 | 说明 |
|---|---|
| `search_financing_companies` | 早期获投企业列表（时间/产业/区域/轮次/金额多维筛选，首页 10 家自动补全工商画像） |
| `get_industryFund_list` | 产业基金列表（区域/关键词筛选） |
| `search_industryFund_investmen_list` | 批量基金投资事件（轮次/产业/区域/状态筛选） |
| `get_industryFund_exit_list` | 批量基金退出事件（日期/退出方式筛选，自动补全基金简介） |
| `get_fund_detail_basic` | 基金基本信息（基金名称自动消歧） |
| `get_fund_detail_investor_list` | 基金出资人列表 |
| `get_fund_detail_investment_list` | 基金投资明细（自动补全投资金额/持股比例） |
| `get_fund_detail_exit_list` | 基金退出明细 |
| `get_query_competitive_Finance` | 竞品融资差异对比（多维相似度 + 融资阶段快照对比） |

### 2. enterprise-mcp（企业 Sever）
- **端口**: 8908
- **路径**: `/cece-mcp-servers/enterprise/stream`
- **工具数**: 17

| 工具 | 说明 |
|---|---|
| `get_enterprise_tags` | 企业标签（资本市场/科技/榜单/标准制定/产业/风险） |
| `get_enterprise_basic` | 企业工商信息（经营状态/注册资本/法人/成立日期等） |
| `get_enterprise_shareholders` | 股东信息（上市公告 + 工商登记双口径） |
| `get_enterprise_management` | 主要人员/董监高（上市公告 + 工商登记 + 投资任职） |
| `get_enterprise_VCPE_financing` | 创投融资（轮次筛选） |
| `get_enterprise_stock_financing` | 股票融资（A股IPO/增发/配股/港股IPO等） |
| `get_enterprise_bond_financing` | 债券融资（评级过滤） |
| `get_enterprise_bondHolder` | 债券持有人 |
| `get_enterprise_bank_financing` | 银行借款 |
| `get_enterprise_receivables_financing` | 应收账款融资 |
| `get_enterprise_leasing_financing` | 租赁融资 |
| `get_enterprise_trust_financing` | 信托融资 |
| `get_enterprise_credit_financing` | 授信额度 |
| `get_enterprise_outbound_investment` | 对外投资 |
| `get_company_graphy` | 企业关系图谱（四层血缘，支持迭代展开） |
| `get_businessFinance_graphy` | 融资关系图谱 |
| `get_query_winTenderer_tenderee` | 招投标信息（招标方 + 投标方） |

### 3. person-insight-mcp（人物 Sever）
- **端口**: 8909
- **路径**: `/cece-mcp-servers/person/stream`
- **工具数**: 8

| 工具 | 说明 |
|---|---|
| `get_person_legal` | 法定代表人任职企业 |
| `get_person_office` | 在外任职企业 |
| `get_person_beneficial` | 受益所有人企业 |
| `get_person_controller` | 实际控制人企业 |
| `get_person_holder` | 直接/间接持股企业（含持股路径可视化） |
| `get_person_union` | 关联企业（含角色分布） |
| `get_person_partner` | 合作伙伴（含合作详情） |
| `get_talent_basic` | 人才基本信息（科技人才 + 人物简介） |

### 4. entity-resolve-mcp（主体识别 Sever）
- **端口**: 8910
- **路径**: `/cece-mcp-servers/NER/stream`
- **工具数**: 4

| 工具 | 说明 |
|---|---|
| `get_industry_tree` | 产业分类树（简称字典精确匹配 + Milvus 向量语义搜索） |
| `get_region_tree` | 区域选择器树（Dify 地址打标工作流） |
| `search_enterprise_by_name` | 企业名称识别（Dify 工作流，简称/品牌→工商全称） |
| `search_person_by_name` | 人物名称搜索（ES 人物库，含角色/区域分布） |

## MCP 错误规范

遵循 [MCP 规范](https://modelcontextprotocol.io/docs/concepts/tools#error-handling) 的两种错误层次：

| 类型 | MCP 表示 | 适用场景 |
|---|---|---|
| **工具执行错误** | `CallToolResult.isError = true` (通过 `ToolError` 异常实现) | API 调用失败、查询无数据、实体未匹配、参数不合法、无权限 |
| **正常结果** | `CallToolResult.isError = false` | 查询成功、唯一匹配、多候选、未匹配（消歧流程属于正常业务） |

错误状态码采用**集中拦截**机制：`server_factory.register_tools()` 中的 wrapper 自动检测函数返回的 `"状态码"` 或 `status == "error"`，统一转为 `ToolError`，由 FastMCP 框架序列化为 MCP 标准错误响应。

## MCP 鉴权

本服务支持 MCP 标准 OAuth 2.1 鉴权（符合 MCP 规范），由 FastMCP 框架内置支持，不侵入工具逻辑。

### 鉴权方式

**OAuth 2.1 授权码流程（推荐）**：
客户端通过标准的 OAuth 2.1 授权码流程（支持 PKCE）获取 access_token，后续 MCP 请求自动携带。

**客户端凭证流程**：
适用于服务间调用，通过 `client_id` + `client_secret` 直接换取 access_token。

### 启用鉴权

每个服务入口文件（如 `servers/finance_server.py`）已预置 OAuth 2.1 Provider 配置，取消注释即可启用：

```python
from common.auth import create_oauth_provider

SERVICE_KEY = "finance"
OAUTH_PROVIDER = create_oauth_provider(SERVICE_KEY)
mcp = create_mcp(SERVICE_KEY, auth_provider=OAUTH_PROVIDER)
```

### 注册静态客户端（预置凭证）

启用 OAuth 后，可注册静态客户端用于测试：

```python
from common.auth import register_static_client

async def _init():
    await register_static_client(
        OAUTH_PROVIDER,
        client_id="test_client",
        client_secret="test_secret",
    )
```

客户端通过 `client_credentials` 授权类型换取 token：

```bash
curl -X POST http://127.0.0.1:8907/.well-known/oauth/token \
  -d "grant_type=client_credentials" \
  -d "client_id=test_client" \
  -d "client_secret=test_secret" \
  -d "scope=mcp"
```

返回的 `access_token` 在后续 MCP 请求中通过 `Authorization: Bearer <token>` 携带，由 FastMCP 框架自动验证。

### 工具使用记录

所有工具调用完成后自动记录到 `mcp_tool_usage` 表（无需鉴权即可记录），包含：
- 调用的工具名、参数摘要（敏感字段脱敏）
- 执行结果（success / error）和错误信息
- 执行耗时（毫秒）
- 调用来源 IP

该记录依赖 MySQL 数据库，需配置以下环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MCP_DB_HOST` | `192.168.202.147` | MySQL 主机 |
| `MCP_DB_PORT` | `3306` | MySQL 端口 |
| `MCP_DB_USER` | `a_sh_hydc_liyaqi` | MySQL 用户 |
| `MCP_DB_PASSWORD` | `DDDKhsfU@20260605` | MySQL 密码 |
| `MCP_DB_NAME` | `a_sh_ods` | 数据库名 |
| `MCP_AUTH_ENABLED` | `false` | 是否启用鉴权（`true` 启用，本地开发不设） |

## 安装与配置

```bash
pip install -r requirements.txt
```

依赖：`mcp<2`（FastMCP v4）、`httpx`、`pydantic`。

在 `.env` 文件中配置网关凭据（不应提交到 Git）：

```
ENTITY_API_AUTHORIZATION=jwt_xxx
ENTITY_API_XSEC=xxx
```

系统环境变量优先级更高（`export ENTITY_API_AUTHORIZATION=...`），便于 Linux 部署时用环境变量覆盖。

Entity-resolve 服务额外依赖：
- **DashScope**（文本嵌入）：`DASHSCOPE_API_KEY` 环境变量或代码内默认 key
- **Milvus**（向量数据库）：`172.29.19.25:19530`，库 `MCP_NER`，集合 `industry_search`
- **Dify**（工作流服务）：`http://172.20.28.224/v1/workflows/run`，含 3 个 App Key

## 启动

### 开发模式（独立启动）

```bash
python servers/finance_server.py
python servers/enterprise_server.py
python servers/person_insight_server.py
python servers/entity_resolve_server.py
```

### 管理后台

提供用户注册、Token 创建与查询接口，独立端口运行：

```bash
python servers/admin_server.py
```

服务启动在 `http://0.0.0.0:8911`。

### 生产模式（一键启动 + Nginx）

```bash
bash start_all_servers.sh
```

Nginx 反向代理配置见 `mcp.conf`，各服务路径：

| 服务 | 内部端口 | Nginx 路径 |
|---|---|---|
| finance-mcp | 8907 | `/cece-mcp-servers/PEVC/` |
| enterprise-mcp | 8908 | `/cece-mcp-servers/enterprise/` |
| person-insight-mcp | 8909 | `/cece-mcp-servers/person/` |
| entity-resolve-mcp | 8910 | `/cece-mcp-servers/NER/` |

## MCP 客户端连接示例

MCP 客户端（如 ADK Agent）通过 Streamable HTTP 端点连接每个服务：

```
http://mcp-xhzjds.cnfic.com.cn/cece-mcp-servers/PEVC/stream
http://mcp-xhzjds.cnfic.com.cn/cece-mcp-servers/enterprise/stream
http://mcp-xhzjds.cnfic.com.cn/cece-mcp-servers/person/stream
http://mcp-xhzjds.cnfic.com.cn/cece-mcp-servers/NER/stream
```

### 实体查询的典型调用流程

1. **主体识别** → 调用 `entity-resolve-mcp` 的 `search_enterprise_by_name` / `search_person_by_name` 获取标准实体信息
2. **数据查询** → 将标准实体信息传入对应服务的查询工具
3. **错误处理** → "实体未匹配" 时回到步骤 1 重试；"查询无数据" 不触发消歧

## 出参整形管线

所有工具的输出自动经过以下处理（由 `register_tools` 统一执行）：

1. **信封清理** → 移除顶层 `status` / `data` 等透传字段
2. **ID 剔除** → 递归移除 `xxxId` / `xxxID` / `xxx_id` 类字段
3. **键翻译** → 按 `data/field_mapping_*.json` 配置 + 自动翻译词典将英文 key 转为中文
4. **字段筛选** → 按工具功能描述只保留相关字段

## 测试

```bash
# 运行所有测试
python -m unittest discover -s tests

# 或使用 pytest
python -m pytest tests/ -v
```

## 目录说明

```
data/
├── field_mapping_auto.json       # 自动翻译缓存
├── field_mapping_enterprise.json # 企业模块字段映射
├── field_mapping_industry.json   # 产业模块字段映射
└── region_codes.json             # 地区行政区划代码
logs/                             # 运行日志（生产模式）
tests/                            # 单元测试
```