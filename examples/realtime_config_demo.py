"""
MindBot 实时配置系统演示

运行: python -m examples.realtime_config_demo
"""

import asyncio
from pathlib import Path

from mindbot.config import ConfigBus, AgentConfigIntegration
from mindbot.auth.manager import AuthManager


async def demo_config_bus():
    """Phase 1: 配置事件总线演示"""
    print("\n" + "=" * 50)
    print("Phase 1: 配置事件总线 (ConfigBus)")
    print("=" * 50)

    bus = ConfigBus()

    # 设置配置
    await bus.set("global", "temperature", 0.8)
    await bus.set("global", "max_tokens", 2000)

    # 获取配置
    temp = await bus.get("global", "temperature")
    print(f"温度设置: {temp}")

    # 订阅变更
    def on_temp_change(old, new):
        print(f"🌡️ 温度变更: {old} -> {new}")

    bus.subscribe("global", "temperature", on_temp_change)

    # 更新温度 - 会触发回调
    await bus.set("global", "temperature", 1.2)
    await asyncio.sleep(0.1)  # 等待异步通知

    print(f"版本号: {bus.version}")


async def demo_auth_manager():
    """Phase 2: 授权管理器演示"""
    print("\n" + "=" * 50)
    print("Phase 2: 授权管理器 (AuthManager)")
    print("=" * 50)

    bus = ConfigBus()
    auth = AuthManager(bus)

    user_id = "user_demo_123"
    tool_name = "delete_file"

    # 检查未授权
    allowed, reason = await auth.check(user_id, tool_name)
    print(f"未授权检查: allowed={allowed}, reason={reason}")

    # 授予临时授权（5秒）
    await auth.grant(user_id, tool_name, allowed=True, expires_in=5)

    # 检查已授权
    allowed, reason = await auth.check(user_id, tool_name)
    print(f"授权后检查: allowed={allowed}, reason={reason}")

    # 等待过期
    print("等待 6 秒让授权过期...")
    await asyncio.sleep(6)

    # 检查已过期
    allowed, reason = await auth.check(user_id, tool_name)
    print(f"过期后检查: allowed={allowed}, reason={reason}")


async def demo_integration():
    """完整集成演示"""
    print("\n" + "=" * 50)
    print("集成演示 (AgentConfigIntegration)")
    print("=" * 50)

    # 创建集成（禁用持久化用于演示）
    integration = AgentConfigIntegration(enable_persistence=False)
    await integration.initialize()

    # 设置全局配置
    await integration.set("global", "model", "gpt-4")
    await integration.set("global", "temperature", 0.7)

    # 授权用户工具
    await integration.grant_auth("alice", "write_file", allowed=True)
    await integration.grant_auth("alice", "delete_file", allowed=True, expires_in=3600)

    # 检查授权
    for tool in ["write_file", "delete_file", "unknown_tool"]:
        allowed, reason = await integration.check_auth("alice", tool)
        print(f"工具 {tool}: {'✅' if allowed else '❌'} {reason}")

    # 列出用户授权
    auths = await integration.auth.list_user_auth("alice")
    print(f"\nAlice 的授权列表: {list(auths.keys())}")

    await integration.shutdown()


async def demo_persistence():
    """持久化演示"""
    print("\n" + "=" * 50)
    print("Phase 3: 配置持久化")
    print("=" * 50)

    config_path = Path("/tmp/mindbot_demo_config.json")

    # 第一个实例：设置配置并保存
    print("\n[实例 1] 设置配置...")
    integration1 = AgentConfigIntegration(persistence_path=config_path)
    await integration1.initialize()

    await integration1.set("global", "demo_setting", "hello_world")
    await integration1.grant_auth("user_1", "tool_a", allowed=True)

    await asyncio.sleep(0.5)  # 等待保存
    await integration1.shutdown()
    print("[实例 1] 配置已保存")

    # 第二个实例：加载配置
    print("\n[实例 2] 加载配置...")
    integration2 = AgentConfigIntegration(persistence_path=config_path)
    await integration2.initialize()

    value = await integration2.get("global", "demo_setting")
    allowed, _ = await integration2.check_auth("user_1", "tool_a")

    print(f"加载的配置: demo_setting = {value}")
    print(f"加载的授权: user_1/tool_a = {allowed}")

    await integration2.shutdown()

    # 清理
    config_path.unlink(missing_ok=True)


async def demo_realtime_update():
    """实时更新演示"""
    print("\n" + "=" * 50)
    print("实时更新演示")
    print("=" * 50)

    bus = ConfigBus()

    # 模拟 Agent 配置更新
    config_state = {"temperature": 0.7, "system_prompt": "You are helpful."}

    def on_config_change(key, old, new):
        def callback(o, n):
            config_state[key] = n
            print(f"  [实时更新] {key}: {o} -> {n}")
        return callback

    bus.subscribe("agent", "temperature", on_config_change("temperature", None, None))
    bus.subscribe("agent", "system_prompt", on_config_change("system_prompt", None, None))

    print("初始状态:", config_state)

    # 模拟外部配置更新
    print("\n模拟外部配置更新...")
    await bus.set("agent", "temperature", 1.0)
    await bus.set("agent", "system_prompt", "You are creative.")

    await asyncio.sleep(0.1)

    print("\n最终状态:", config_state)


async def main():
    """主演示"""
    print("\n" + "=" * 50)
    print("MindBot 实时配置系统演示")
    print("=" * 50)

    await demo_config_bus()
    await demo_auth_manager()
    await demo_integration()
    await demo_persistence()
    await demo_realtime_update()

    print("\n" + "=" * 50)
    print("演示完成!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
