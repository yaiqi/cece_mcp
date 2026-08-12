# Entity MCP 交接说明

## 当前状态

- 已从单一 MCP 服务拆分为 company、group、industry、park、person、region 六个 Streamable HTTP 服务。
- 消歧工具单独暴露；查询工具不在内部自动消歧。
- 已统一中文业务状态码，并限制候选列表最多 5 项。
- 园区消歧对外不暴露 Milvus `score`；Milvus 认证读取 `MILVUS_USER`、`MILVUS_PASSWORD`。
- `park_company_features` 先调 `tabcompanycount` 取得“全部企业”数量，再调 `companyfeatures`，并合并两份数据。
- 区域园区能力均在 `region-mcp`：园区列表、地区分布、统计、开发区列表。
- 标准实体引用模型位于 `models/entity_refs.py`，园区、集团、产业、人物、区域查询已使用对应模型注解。

## 关键入口

- 服务配置：`common/server_factory.py`
- 服务入口：`servers/*_server.py`
- 标准引用模型：`models/entity_refs.py`
- 业务状态协议：`common/business_protocol.py`
- 环境变量模板需自行创建：`.env`（不得提交）

## 后续建议

1. 使用 MCP Inspector 或 ADK 逐个验证 `tools/list` 的 Pydantic Schema 是否符合预期。
2. 清理各实体工具中仍提及旧参数名的 docstring。
3. 对 company/group/industry/person/region 消歧异常补齐与园区相同的“调用失败”保护。
4. 评估园区 Milvus 相似度阈值和候选排序，防止语义误匹配。

## 验证命令

```bash
python -m unittest discover -s entity_mcp/tests -v
python -m compileall -q entity_mcp
```
