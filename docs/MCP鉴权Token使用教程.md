# MCP 鉴权 Token 使用教程

## 概述

MCP 服务支持 Bearer Token 鉴权。用户通过管理后台注册并获取 Token，在调用 MCP 工具时在 HTTP Header 中传入 `Authorization: Bearer <token>` 完成鉴权。

Token 采用 SHA-256 哈希存储于数据库，数据库不保存明文。创建 Token 时明文仅返回一次，请妥善保存。

###  配置 MCP 客户端

在 MCP 客户端的 HTTP Header 中添加鉴权信息：

| Header | 值 |
|--------|-----|
| `Authorization` | `Bearer 894c98bebec8a0c03cba633a66d32d276e9c490a410dbcfd3cba832d175c2867` |
| `Content-Type` | `application/json` |



## 错误处理

| 错误信息 | 说明 | 处理方式 |
|----------|------|----------|
| `缺少或无效的 Authorization Token` | 未传入 Header 或格式错误 | 检查是否添加 `Authorization: Bearer <token>` |
| `Token 不存在或已失效` | Token 值错误或从未存在 | 检查 Token 是否拼写正确，或重新创建 |
| `Token 已被禁用` | 管理员已禁用该 Token | 联系管理员或创建新 Token |
| `Token 已过期` | 超过 `expires_at` 有效期 | 创建新 Token |

---

## 注意事项

1. **Token 明文仅创建时返回一次**，丢失后无法找回，需重新创建
2. **Token 有效期默认为 365 天**，过期后需重新创建
3. **Token 名称（token_name）** 用于标识用途（如"办公电脑"、"开发环境"），便于管理
4. **一个用户可创建多个 Token**，分别用于不同场景