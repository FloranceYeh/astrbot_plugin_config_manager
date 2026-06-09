import asyncio
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools


class ConfigPathError(ValueError):
    pass


class AstrBotPluginConfigManager(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir()

    @filter.command("插件配置帮助", alias={"plugin-config-help", "pconf-help"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def config_help(self, event: AstrMessageEvent):
        """显示插件配置管理命令帮助。"""
        try:
            yield event.plain_result(
                "\n".join(
                    [
                        "插件配置管理命令：",
                        "1. 插件配置列表",
                        "2. 插件配置查看 <插件名>",
                        "3. 插件配置获取 <插件名> <键路径>",
                        "4. 插件配置设置 <插件名> <键路径> <值>",
                        "5. 插件配置删除 <插件名> <键路径>",
                        "6. 插件配置备份 <插件名>",
                        "7. 插件配置备份列表 <插件名>",
                        "8. 插件配置恢复 <插件名> <备份文件名>",
                        "",
                        "键路径支持点号访问，例如：server.port、providers.0.model",
                        "设置值会优先按 JSON 解析；解析失败时按普通字符串写入。",
                    ]
                )
            )
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置列表", alias={"plugin-config-list", "pconf-list"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_configs(self, event: AstrMessageEvent):
        """列出当前可管理的插件配置文件。"""
        try:
            config_dir = self._get_config_dir()
            if not config_dir.exists():
                yield event.plain_result(f"配置目录不存在：{config_dir}")
                return

            config_files = sorted(config_dir.glob("*_config.json"))
            if not config_files:
                yield event.plain_result(f"未在 {config_dir} 中发现插件配置文件。")
                return

            lines = [f"配置目录：{config_dir}", "可管理插件："]
            for path in config_files:
                plugin_name = path.name[: -len("_config.json")]
                lines.append(f"- {plugin_name}")
            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置查看", alias={"plugin-config-view", "pconf-view"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def view_config(self, event: AstrMessageEvent, plugin_name: str):
        """查看指定插件的完整配置。"""
        try:
            config_path = self._get_plugin_config_path(plugin_name)
            config_data = await self._load_json(config_path)
            rendered = self._render_json(config_data)
            preview_limit = self._get_int_config("preview_limit", 3500)
            if len(rendered) > preview_limit:
                rendered = (
                    f"{rendered[:preview_limit]}\n... 已截断，共 {len(rendered)} 个字符。"
                )
            yield event.plain_result(f"{config_path.name}\n{rendered}")
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置获取", alias={"plugin-config-get", "pconf-get"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def get_config_value(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        key_path: str,
    ):
        """读取指定插件配置中的某个键。"""
        try:
            config_path = self._get_plugin_config_path(plugin_name)
            config_data = await self._load_json(config_path)
            value = self._get_by_path(config_data, self._parse_key_path(key_path))
            yield event.plain_result(self._render_json(value))
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置设置", alias={"plugin-config-set", "pconf-set"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def set_config_value(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        key_path: str,
        value: str,
    ):
        """写入指定插件配置中的某个键。"""
        try:
            config_path = self._get_plugin_config_path(plugin_name, allow_missing=True)
            config_data = await self._load_json(config_path, allow_missing=True)
            parsed_value = self._parse_input_value(value)
            if config_path.exists():
                await self._create_backup(plugin_name, config_path)
            self._set_by_path(config_data, self._parse_key_path(key_path), parsed_value)
            await self._save_json(config_path, config_data)
            logger.info(f"updated config for {plugin_name}: {key_path}")
            yield event.plain_result(f"已写入 {plugin_name}.{key_path}")
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置删除", alias={"plugin-config-del", "pconf-del"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_config_value(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        key_path: str,
    ):
        """删除指定插件配置中的某个键。"""
        try:
            config_path = self._get_plugin_config_path(plugin_name)
            config_data = await self._load_json(config_path)
            await self._create_backup(plugin_name, config_path)
            self._delete_by_path(config_data, self._parse_key_path(key_path))
            await self._save_json(config_path, config_data)
            logger.info(f"deleted config value for {plugin_name}: {key_path}")
            yield event.plain_result(f"已删除 {plugin_name}.{key_path}")
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置备份", alias={"plugin-config-backup", "pconf-backup"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def backup_config(self, event: AstrMessageEvent, plugin_name: str):
        """为指定插件配置创建备份。"""
        try:
            config_path = self._get_plugin_config_path(plugin_name)
            backup_path = await self._create_backup(plugin_name, config_path)
            yield event.plain_result(f"已创建备份：{backup_path.name}")
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command(
        "插件配置备份列表",
        alias={"plugin-config-backup-list", "pconf-backup-list"},
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_backups(self, event: AstrMessageEvent, plugin_name: str):
        """列出指定插件的可用备份。"""
        try:
            backup_dir = self._get_backup_dir(plugin_name)
            if not backup_dir.exists():
                yield event.plain_result(f"{plugin_name} 暂无备份。")
                return

            backups = sorted(backup_dir.glob("*.json"), reverse=True)
            if not backups:
                yield event.plain_result(f"{plugin_name} 暂无备份。")
                return

            lines = [f"{plugin_name} 的备份列表："]
            for backup in backups:
                lines.append(f"- {backup.name}")
            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    @filter.command("插件配置恢复", alias={"plugin-config-restore", "pconf-restore"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def restore_config(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        backup_name: str,
    ):
        """从备份恢复指定插件配置。"""
        try:
            backup_path = self._get_backup_path(plugin_name, backup_name)
            if not backup_path.exists():
                raise FileNotFoundError(f"备份不存在：{backup_name}")

            config_path = self._get_plugin_config_path(plugin_name, allow_missing=True)
            if config_path.exists():
                await self._create_backup(plugin_name, config_path)
            restored_data = await self._load_json(backup_path)
            await self._save_json(config_path, restored_data)
            logger.info(f"restored config for {plugin_name} from {backup_name}")
            yield event.plain_result(f"已恢复 {plugin_name}，来源备份：{backup_name}")
        except Exception as exc:
            yield event.plain_result(self._handle_unexpected_error(exc))

    async def terminate(self):
        """插件卸载时调用。"""

    def _get_config_dir(self) -> Path:
        override = str(self._get_raw_config_value("config_dir_override", "")).strip()
        if override:
            return Path(override).expanduser().resolve()
        return self.data_dir.parent.parent / "config"

    def _get_backup_dir(self, plugin_name: str) -> Path:
        return self.data_dir / "backups" / self._sanitize_plugin_name(plugin_name)

    def _get_backup_path(self, plugin_name: str, backup_name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", backup_name):
            raise ConfigPathError("备份文件名非法。")
        backup_dir = self._get_backup_dir(plugin_name).resolve()
        backup_path = (backup_dir / backup_name).resolve()
        if backup_path.parent != backup_dir:
            raise ConfigPathError("备份文件路径越界。")
        return backup_path

    def _get_plugin_config_path(
        self,
        plugin_name: str,
        allow_missing: bool = False,
    ) -> Path:
        safe_name = self._sanitize_plugin_name(plugin_name)
        config_dir = self._get_config_dir().resolve()
        config_path = (config_dir / f"{safe_name}_config.json").resolve()
        if config_path.parent != config_dir:
            raise ConfigPathError("插件名非法，路径越界。")
        if not allow_missing and not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在：{config_path.name}")
        return config_path

    def _sanitize_plugin_name(self, plugin_name: str) -> str:
        candidate = plugin_name.strip()
        if not candidate:
            raise ConfigPathError("插件名不能为空。")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", candidate):
            raise ConfigPathError("插件名仅允许字母、数字、点、下划线和中划线。")
        return candidate

    def _parse_key_path(self, key_path: str) -> list[str | int]:
        raw_parts = [part.strip() for part in key_path.split(".")]
        if not raw_parts or any(part == "" for part in raw_parts):
            raise ConfigPathError("键路径不能为空，且不能包含空段。")

        parsed_parts: list[str | int] = []
        for part in raw_parts:
            if part.isdigit():
                parsed_parts.append(int(part))
            else:
                parsed_parts.append(part)
        return parsed_parts

    def _parse_input_value(self, raw_value: str) -> Any:
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value

    def _get_by_path(self, data: Any, path_parts: list[str | int]) -> Any:
        current = data
        for part in path_parts:
            if isinstance(part, int):
                if not isinstance(current, list):
                    raise ConfigPathError(f"路径段 {part} 不是列表索引。")
                if part >= len(current):
                    raise ConfigPathError(f"列表索引越界：{part}")
                current = current[part]
                continue

            if not isinstance(current, dict):
                raise ConfigPathError(f"路径段 {part} 的父节点不是对象。")
            if part not in current:
                raise ConfigPathError(f"键不存在：{part}")
            current = current[part]
        return current

    def _set_by_path(self, data: Any, path_parts: list[str | int], value: Any):
        if not isinstance(data, dict):
            raise ConfigPathError("配置根节点必须是 JSON 对象。")

        current = data
        for index, part in enumerate(path_parts[:-1]):
            next_part = path_parts[index + 1]
            if isinstance(part, int):
                if not isinstance(current, list):
                    raise ConfigPathError(f"路径段 {part} 的父节点不是列表。")
                while len(current) <= part:
                    current.append({} if isinstance(next_part, str) else [])
                if not isinstance(current[part], (dict, list)):
                    current[part] = {} if isinstance(next_part, str) else []
                current = current[part]
                continue

            if not isinstance(current, dict):
                raise ConfigPathError(f"路径段 {part} 的父节点不是对象。")
            if part not in current or not isinstance(current[part], (dict, list)):
                current[part] = {} if isinstance(next_part, str) else []
            current = current[part]

        last_part = path_parts[-1]
        if isinstance(last_part, int):
            if not isinstance(current, list):
                raise ConfigPathError(f"最终路径段 {last_part} 的父节点不是列表。")
            while len(current) <= last_part:
                current.append(None)
            current[last_part] = value
            return

        if not isinstance(current, dict):
            raise ConfigPathError(f"最终路径段 {last_part} 的父节点不是对象。")
        current[last_part] = value

    def _delete_by_path(self, data: Any, path_parts: list[str | int]):
        current = data
        for part in path_parts[:-1]:
            current = self._get_by_path(current, [part])

        last_part = path_parts[-1]
        if isinstance(last_part, int):
            if not isinstance(current, list):
                raise ConfigPathError(f"最终路径段 {last_part} 的父节点不是列表。")
            if last_part >= len(current):
                raise ConfigPathError(f"列表索引越界：{last_part}")
            current.pop(last_part)
            return

        if not isinstance(current, dict):
            raise ConfigPathError(f"最终路径段 {last_part} 的父节点不是对象。")
        if last_part not in current:
            raise ConfigPathError(f"键不存在：{last_part}")
        del current[last_part]

    def _render_json(self, data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _get_raw_config_value(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        getter = getattr(self.config, "get", None)
        if callable(getter):
            return getter(key, default)
        return getattr(self.config, key, default)

    def _get_int_config(self, key: str, default: int) -> int:
        raw_value = self._get_raw_config_value(key, default)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return default

    def _handle_unexpected_error(self, exc: Exception) -> str:
        if isinstance(exc, (ConfigPathError, FileNotFoundError, json.JSONDecodeError)):
            logger.warning(f"config manager command failed: {exc}")
            return f"操作失败：{exc}"
        logger.error(f"config manager command failed unexpectedly: {exc}")
        return "操作失败：内部错误，请查看日志。"

    async def _load_json(
        self,
        path: Path,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        if not path.exists():
            if allow_missing:
                return {}
            raise FileNotFoundError(f"配置文件不存在：{path.name}")

        def _reader() -> dict[str, Any]:
            with path.open("r", encoding="utf-8") as file:
                content = json.load(file)
            if not isinstance(content, dict):
                raise ConfigPathError("配置根节点必须是 JSON 对象。")
            return content

        return await asyncio.to_thread(_reader)

    async def _save_json(self, path: Path, data: dict[str, Any]):
        if not isinstance(data, dict):
            raise ConfigPathError("配置根节点必须是 JSON 对象。")

        def _writer():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f"{path.name}.tmp")
            payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            with temp_path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(payload)
            os.replace(temp_path, path)

        await asyncio.to_thread(_writer)

    async def _create_backup(self, plugin_name: str, config_path: Path) -> Path:
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在：{config_path.name}")

        backup_dir = self._get_backup_dir(plugin_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_dir / f"{timestamp}.json"

        def _backup():
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_path, backup_path)

        await asyncio.to_thread(_backup)
        await self._trim_backups(backup_dir)
        return backup_path

    async def _trim_backups(self, backup_dir: Path):
        keep_count = max(1, self._get_int_config("backup_keep_count", 10))

        def _cleanup():
            backups = sorted(backup_dir.glob("*.json"), reverse=True)
            for obsolete in backups[keep_count:]:
                obsolete.unlink(missing_ok=True)

        await asyncio.to_thread(_cleanup)
