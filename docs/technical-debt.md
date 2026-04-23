# 技术债务记录

## PermissionManager 兼容性方法

### 概述
PermissionManager 保留了旧 ApprovalManager 的 API 方法用于向后兼容。这些方法应该在 v0.5 或 v1.0 版本中移除。

### 待移除的方法

| 方法 | 状态 | 替代方案 | 备注 |
|------|------|----------|------|
| `request_approval(tool_name, arguments, ...)` | 兼容 | `request_permission(PermissionRequest, ...)` | 使用新 API 更灵活 |
| `add_to_whitelist(tool_name, pattern)` | 兼容 | 通过 `GRANT_ALWAYS` 决策自动持久化 | 新 API 自动处理白名单 |
| `remove_from_whitelist(tool_name, pattern)` | 兼容 | `revoke_grant(permission_type, resource)` | 新 API 更通用 |
| `is_whitelisted(tool_name, arguments)` | 兼容 | `check_permission(permission_type, resource)` | 新 API 支持多种权限类型 |
| `resolve(request_id, decision)` | 兼容 | `resolve_from_message(request_id, message)` | 新 API 支持自然语言 |
| `get_pending_requests()` | 兼容 | `get_pending_request(request_id)` | 方法名更精确 |

### 迁移示例

#### 旧代码（需要迁移）
```python
from mindbot.permissions import PermissionManager

pm = PermissionManager(config=config, config_path=config_path)

# 检查白名单
if not pm.is_whitelisted("delete_file", {"path": "/tmp/test"}):
    # 请求授权
    decision = await pm.request_approval(
        "delete_file",
        {"path": "/tmp/test"},
        on_event=event_handler,
    )
    if decision == ApprovalDecision.ALLOW_ALWAYS:
        pm.add_to_whitelist("delete_file", ".*")
```

#### 新代码（推荐）
```python
from mindbot.permissions import (
    PermissionManager,
    PermissionRequest,
    PermissionType,
    PermissionDecision,
)

pm = PermissionManager(config=config, config_path=config_path)

# 检查权限
is_granted, reason = pm.check_permission(
    PermissionType.TOOL_EXECUTION,
    "delete_file"
)

if not is_granted:
    # 创建权限请求
    request = PermissionRequest(
        request_id=str(uuid.uuid4()),
        permission_type=PermissionType.TOOL_EXECUTION,
        resource="delete_file",
        context={"arguments": {"path": "/tmp/test"}},
        reason="用户请求删除临时文件",
        risk_level="high",
    )

    # 请求授权（支持自然语言回复）
    decision = await pm.request_permission(
        request,
        on_event=event_handler,
    )

    # GRANT_ALWAYS 会自动持久化到配置文件
```

### 移除计划

**目标版本**: v0.5 或 v1.0

**移除步骤**:
1. 在 CHANGELOG 中标记这些方法为 deprecated
2. 添加 deprecation warnings
3. 在目标版本中移除方法
4. 更新文档

### 相关文件

- `src/mindbot/permissions/permission_manager.py`
  - 所有兼容性方法都在 `PermissionManager` 类中，标记为 `"Compatibility method for ApprovalManager.xxx()"`

### 影响评估

**低风险**: 这些方法只是旧 API 的包装，内部都调用新的 `PermissionManager` 实现。

**迁移成本**: 低 - 用户只需更改方法调用，逻辑不变。

---

## 记录时间
- 创建: 2026-04-23
- 计划移除: v0.5 或 v1.0
