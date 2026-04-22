"""实时配置系统内置 Skill

允许通过自然语言更新配置，例如：
- "设置温度为 0.8"
- "授权用户 delete_file 工具"
- "查看当前配置"
"""

from typing import Any

from mindbot.config import AgentConfigIntegration
from mindbot.skills.models import Skill, SkillParameter


class ConfigSkill:
    """配置管理 Skill"""

    def __init__(self):
        self.integration = None

    def _get_integration(self) -> AgentConfigIntegration:
        """延迟初始化 ConfigIntegration"""
        if self.integration is None:
            import asyncio
            from pathlib import Path
            self.integration = AgentConfigIntegration(
                persistence_path=Path.home() / ".mindbot" / "config_store.json",
                enable_persistence=True,
            )
            # 同步初始化
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import asyncio
                    asyncio.create_task(self.integration.initialize())
                else:
                    loop.run_until_complete(self.integration.initialize())
            except RuntimeError:
                # 没有事件循环，创建新的
                asyncio.run(self.integration.initialize())
        return self.integration

    def get_skills(self) -> list[Skill]:
        """返回所有配置相关的 skills"""
        return [
            Skill(
                name="config_set",
                description="设置配置值，支持全局配置和用户级别配置",
                parameters=[
                    SkillParameter(
                        name="scope",
                        type="string",
                        description="配置作用域，如 'global', 'user:123', 'session:abc'",
                    ),
                    SkillParameter(
                        name="key",
                        type="string",
                        description="配置键名",
                    ),
                    SkillParameter(
                        name="value",
                        type="string",
                        description="配置值",
                    ),
                ],
                handler=self._handle_config_set,
            ),
            Skill(
                name="config_get",
                description="获取配置值",
                parameters=[
                    SkillParameter(
                        name="scope",
                        type="string",
                        description="配置作用域",
                    ),
                    SkillParameter(
                        name="key",
                        type="string",
                        description="配置键名",
                    ),
                ],
                handler=self._handle_config_get,
            ),
            Skill(
                name="config_list",
                description="列出所有配置或指定作用域的配置",
                parameters=[
                    SkillParameter(
                        name="scope",
                        type="string",
                        description="配置作用域（可选，为空则列出所有）",
                        required=False,
                    ),
                ],
                handler=self._handle_config_list,
            ),
            Skill(
                name="auth_grant",
                description="授权用户使用指定工具",
                parameters=[
                    SkillParameter(
                        name="user_id",
                        type="string",
                        description="用户ID",
                    ),
                    SkillParameter(
                        name="tool_name",
                        type="string",
                        description="工具名称",
                    ),
                    SkillParameter(
                        name="expires_in",
                        type="integer",
                        description="过期时间（秒），为空表示永久",
                        required=False,
                    ),
                ],
                handler=self._handle_auth_grant,
            ),
            Skill(
                name="auth_revoke",
                description="撤销用户对工具的授权",
                parameters=[
                    SkillParameter(
                        name="user_id",
                        type="string",
                        description="用户ID",
                    ),
                    SkillParameter(
                        name="tool_name",
                        type="string",
                        description="工具名称",
                    ),
                ],
                handler=self._handle_auth_revoke,
            ),
            Skill(
                name="auth_check",
                description="检查用户是否有权使用工具",
                parameters=[
                    SkillParameter(
                        name="user_id",
                        type="string",
                        description="用户ID",
                    ),
                    SkillParameter(
                        name="tool_name",
                        type="string",
                        description="工具名称",
                    ),
                ],
                handler=self._handle_auth_check,
            ),
        ]

    async def _handle_config_set(self, scope: str, key: str, value: str) -> str:
        """处理配置设置"""
        integration = self._get_integration()

        # 尝试转换值为合适的类型
        converted_value = self._convert_value(value)

        await integration.set(scope, key, converted_value)
        return f"✓ 已设置 {scope}.{key} = {converted_value}（类型: {type(converted_value).__name__}）"

    async def _handle_config_get(self, scope: str, key: str) -> str:
        """处理配置获取"""
        integration = self._get_integration()
        value = await integration.get(scope, key)

        if value is None:
            return f"⚠ {scope}.{key} 未设置"
        return f"{scope}.{key} = {value}（类型: {type(value).__name__}）"

    async def _handle_config_list(self, scope: str = None) -> str:
        """处理配置列表"""
        integration = self._get_integration()

        lines = ["📋 配置列表:"]

        if scope:
            configs = integration.bus.get_scope(scope)
            if not configs:
                lines.append(f"  {scope}: (无配置)")
            else:
                lines.append(f"  [{scope}]")
                for key, value in configs.items():
                    lines.append(f"    {key} = {value}")
        else:
            all_scopes = list(integration.bus._store.keys())
            if not all_scopes:
                lines.append("  (无任何配置)")
            else:
                for scope_name in sorted(all_scopes):
                    configs = integration.bus.get_scope(scope_name)
                    if configs:
                        lines.append(f"  [{scope_name}]")
                        for key, value in configs.items():
                            lines.append(f"    {key} = {value}")

        return "\n".join(lines)

    async def _handle_auth_grant(
        self,
        user_id: str,
        tool_name: str,
        expires_in: int = None,
    ) -> str:
        """处理授权"""
        integration = self._get_integration()

        await integration.grant_auth(user_id, tool_name, allowed=True, expires_in=expires_in)

        if expires_in:
            return f"✓ 已授权 {user_id} 使用 {tool_name}（{expires_in}秒后过期）"
        return f"✓ 已授权 {user_id} 使用 {tool_name}（永久有效）"

    async def _handle_auth_revoke(self, user_id: str, tool_name: str) -> str:
        """处理撤销授权"""
        integration = self._get_integration()
        await integration.auth.revoke(user_id, tool_name)
        return f"✓ 已撤销 {user_id} 对 {tool_name} 的授权"

    async def _handle_auth_check(self, user_id: str, tool_name: str) -> str:
        """处理授权检查"""
        integration = self._get_integration()
        allowed, reason = await integration.check_auth(user_id, tool_name)

        if allowed:
            return f"✓ {user_id} 可以使用 {tool_name}（{reason}）"
        return f"✗ {user_id} 不能使用 {tool_name}（{reason}）"

    def _convert_value(self, value: str) -> Any:
        """尝试将字符串转换为合适的类型"""
        # 尝试整数
        try:
            return int(value)
        except ValueError:
            pass

        # 尝试浮点数
        try:
            return float(value)
        except ValueError:
            pass

        # 布尔值
        lower = value.lower()
        if lower in ("true", "yes", "on", "1"):
            return True
        if lower in ("false", "no", "off", "0"):
            return False

        # 保持字符串
        return value


# 导出技能实例
config_skill = ConfigSkill()
SKILLS = config_skill.get_skills()
