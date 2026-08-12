# 架构

## 分层

```text
servers/      服务入口、端口、路由、工具注册
entities/     各实体的业务工具和上游接口编排
models/       MCP 可见的输入模型与标准实体引用
common/       网关客户端、Milvus 客户端、状态协议、服务工厂
data/         本地行政区划等静态数据
```

`common/server_factory.py` 是六个服务的共享入口工厂。路由由 `SERVICE_CONFIGS` 生效；各 server 文件中的 `ROUTE` 仅供测试和可读性使用。

## 实体引用

查询工具不应接受简称或自行消歧，而应接收对应的标准引用模型。模型定义在 `models/entity_refs.py`，包括 `CompanyRef`、`GroupRef`、`IndustryRef`、`ParkRef`、`PersonRef`、`RegionRef`。

以园区为例，先调用 `resolve_park`，当结果为“唯一匹配”时，将其 `标准实体` 原样传给园区查询工具。`ParkRef` 的必填字段为 `park_id`、`zjs_park_id`、`park_name`。

## 部署边界

`entity_mcp` 不依赖 `my_agent`。生产环境可将其作为独立项目、独立镜像或独立进程部署；Agent 仅通过 Streamable HTTP 地址访问服务。
