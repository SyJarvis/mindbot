"""Tests for real-time config system (Phase 1-3)"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from mindbot.config.bus import ConfigBus
from mindbot.auth.manager import AuthManager, ToolAuth
from mindbot.config.persistence import ConfigPersistence
from mindbot.config.integration import AgentConfigIntegration


class TestConfigBus:
    """Phase 1: Core Event Bus Tests"""

    @pytest.mark.asyncio
    async def test_basic_set_get(self):
        """测试基本读写"""
        bus = ConfigBus()

        await bus.set("global", "temperature", 0.9)
        result = await bus.get("global", "temperature")

        assert result == 0.9

    @pytest.mark.asyncio
    async def test_get_default(self):
        """测试默认值"""
        bus = ConfigBus()

        result = await bus.get("global", "nonexistent", "default_value")

        assert result == "default_value"

    @pytest.mark.asyncio
    async def test_subscribe_notification(self):
        """测试订阅通知"""
        bus = ConfigBus()
        notifications = []

        def callback(old, new):
            notifications.append((old, new))

        bus.subscribe("global", "temperature", callback)
        await bus.set("global", "temperature", 0.8)

        # 等待异步通知
        await asyncio.sleep(0.1)

        assert len(notifications) == 1
        assert notifications[0] == (None, 0.8)

    @pytest.mark.asyncio
    async def test_subscribe_update(self):
        """测试更新时通知"""
        bus = ConfigBus()
        notifications = []

        def callback(old, new):
            notifications.append((old, new))

        # 先设置初始值（会触发通知）
        await bus.set("global", "temperature", 0.7)
        await asyncio.sleep(0.05)

        # 订阅
        bus.subscribe("global", "temperature", callback)

        # 更新值
        await bus.set("global", "temperature", 0.9)

        # 等待异步通知
        await asyncio.sleep(0.1)

        assert len(notifications) == 1
        assert notifications[0] == (0.7, 0.9)

    @pytest.mark.asyncio
    async def test_version_increment(self):
        """测试版本号递增"""
        bus = ConfigBus()

        initial_version = bus.version
        await bus.set("global", "key1", "value1")
        version1 = bus.version
        await bus.set("global", "key2", "value2")
        version2 = bus.version

        assert version1 == initial_version + 1
        assert version2 == initial_version + 2

    @pytest.mark.asyncio
    async def test_get_scope(self):
        """测试获取整个 scope"""
        bus = ConfigBus()

        await bus.set("user:123", "name", "Alice")
        await bus.set("user:123", "age", 30)

        scope = bus.get_scope("user:123")

        assert scope == {"name": "Alice", "age": 30}

    @pytest.mark.asyncio
    async def test_delete(self):
        """测试删除配置"""
        bus = ConfigBus()

        await bus.set("global", "temp", "value")
        result = await bus.delete("global", "temp")

        assert result is True
        assert await bus.get("global", "temp") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """测试删除不存在的配置"""
        bus = ConfigBus()

        result = await bus.delete("global", "nonexistent")

        assert result is False


class TestAuthManager:
    """Phase 2: Auth Manager Tests"""

    @pytest.mark.asyncio
    async def test_grant_and_check(self):
        """测试授权和检查"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        await auth.grant("user_123", "delete_file", allowed=True)
        allowed, reason = await auth.check("user_123", "delete_file")

        assert allowed is True
        assert reason == "已授权"

    @pytest.mark.asyncio
    async def test_check_unauthorized(self):
        """测试未授权检查"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        allowed, reason = await auth.check("user_123", "unknown_tool")

        assert allowed is False
        assert reason == "未授权"

    @pytest.mark.asyncio
    async def test_revoke(self):
        """测试撤销授权"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        await auth.grant("user_123", "tool1", allowed=True)
        await auth.revoke("user_123", "tool1")
        allowed, reason = await auth.check("user_123", "tool1")

        assert allowed is False
        assert reason == "未授权"

    @pytest.mark.asyncio
    async def test_grant_with_expiration(self):
        """测试带过期时间的授权"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        # 授权 0.1 秒后过期
        await auth.grant("user_123", "temp_tool", allowed=True, expires_in=0.1)

        # 立即检查 - 应该有效
        allowed, _ = await auth.check("user_123", "temp_tool")
        assert allowed is True

        # 等待过期
        await asyncio.sleep(0.2)

        # 再次检查 - 应该过期
        allowed, reason = await auth.check("user_123", "temp_tool")
        assert allowed is False
        assert reason == "授权已过期"

    @pytest.mark.asyncio
    async def test_deny_auth(self):
        """测试拒绝授权"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        await auth.grant("user_123", "dangerous_tool", allowed=False)
        allowed, reason = await auth.check("user_123", "dangerous_tool")

        assert allowed is False
        assert reason == "已拒绝"

    @pytest.mark.asyncio
    async def test_list_user_auth(self):
        """测试列出用户授权"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        await auth.grant("user_123", "tool1", allowed=True)
        await auth.grant("user_123", "tool2", allowed=False)

        auths = await auth.list_user_auth("user_123")

        assert "tool1" in auths
        assert "tool2" in auths
        assert auths["tool1"].allowed is True
        assert auths["tool2"].allowed is False

    @pytest.mark.asyncio
    async def test_clear_user_auth(self):
        """测试清除用户授权"""
        bus = ConfigBus()
        auth = AuthManager(bus)

        await auth.grant("user_123", "tool1", allowed=True)
        await auth.clear_user_auth("user_123")

        auths = await auth.list_user_auth("user_123")

        assert len(auths) == 0


class TestConfigPersistence:
    """Phase 3: Persistence Tests"""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """测试保存和加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            # 创建并保存
            bus1 = ConfigBus()
            persistence1 = ConfigPersistence(bus1, path, save_interval=0.1)
            await persistence1.start()

            await bus1.set("global", "temperature", 0.8)
            await bus1.set("user:123", "name", "Alice")

            # 等待保存
            await asyncio.sleep(0.2)
            await persistence1.stop()

            # 加载到新 bus
            bus2 = ConfigBus()
            persistence2 = ConfigPersistence(bus2, path)
            await persistence2.load()

            assert await bus2.get("global", "temperature") == 0.8
            assert await bus2.get("user:123", "name") == "Alice"

    @pytest.mark.asyncio
    async def test_force_save(self):
        """测试强制保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            bus = ConfigBus()
            persistence = ConfigPersistence(bus, path)

            await bus.set("key", "value", "test")
            await persistence.force_save()

            assert path.exists()


class TestAgentConfigIntegration:
    """Integration Tests"""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """测试完整工作流"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            integration = AgentConfigIntegration(persistence_path=path)
            await integration.initialize()

            # 设置配置
            await integration.set("global", "temperature", 0.9)

            # 授权
            await integration.grant_auth("user_123", "delete_file", allowed=True)

            # 检查
            temp = await integration.get("global", "temperature")
            allowed, _ = await integration.check_auth("user_123", "delete_file")

            assert temp == 0.9
            assert allowed is True

            await integration.shutdown()

    @pytest.mark.asyncio
    async def test_subscribe(self):
        """测试订阅功能"""
        integration = AgentConfigIntegration(enable_persistence=False)
        await integration.initialize()

        notifications = []

        def callback(old, new):
            notifications.append((old, new))

        integration.subscribe("global", "temp", callback)
        await integration.set("global", "temp", "value")

        await asyncio.sleep(0.1)

        assert len(notifications) == 1
        assert notifications[0] == (None, "value")

        await integration.shutdown()


class TestToolAuth:
    """ToolAuth dataclass tests"""

    def test_is_expired_no_expiry(self):
        """测试无过期时间的情况"""
        auth = ToolAuth("tool1", allowed=True, expires_at=None)
        assert auth.is_expired() is False

    def test_is_expired_future(self):
        """测试未来过期时间"""
        auth = ToolAuth("tool1", allowed=True, expires_at=time.time() + 3600)
        assert auth.is_expired() is False

    def test_is_expired_past(self):
        """测试已过期"""
        auth = ToolAuth("tool1", allowed=True, expires_at=time.time() - 1)
        assert auth.is_expired() is True

    def test_to_dict(self):
        """测试序列化"""
        auth = ToolAuth("tool1", allowed=True, expires_at=123.0)
        data = auth.to_dict()

        assert data["tool_name"] == "tool1"
        assert data["allowed"] is True
        assert data["expires_at"] == 123.0

    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "tool_name": "tool1",
            "allowed": True,
            "expires_at": 123.0,
            "granted_at": 100.0,
        }
        auth = ToolAuth.from_dict(data)

        assert auth.tool_name == "tool1"
        assert auth.allowed is True
        assert auth.expires_at == 123.0
        assert auth.granted_at == 100.0


import time
