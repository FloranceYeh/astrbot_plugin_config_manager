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

from .core.render import ConfigEntry, RenderHelper


class ConfigPathError(ValueError):
    pass


class AstrBotPluginConfigManager(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir()
        self.renderer = RenderHelper(
            data_dir=self.data_dir,
            int_config_getter=self._get_int_config,
        )

    @filter.command("插件配置帮助", alias={"plugin-config-help", "pconf-help"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def config_help(self, event: AstrMessageEvent):
        """显示插件配置管理命令帮助。"""
        message = "\n".join(
            [
                "插件配置管理命令：",
                "1. 插件配置列表",
                "2. 插件配置查看 <插件名|序号>",
                "3. 插件配置获取 <插件名|序号> <键路径|序号>",
                "4. 插件配置设置 <插件名|序号> <键路径|序号> <值>",
                "5. 插件配置删除 <插件名|序号> <键路径|序号>",
                "6. 插件配置备份 <插件名|序号>",
                "7. 插件配置备份列表 <插件名|序号>",
                "8. 插件配置恢复 <插件名|序号> <备份文件名>",
                "9. 插件配置预设保存 <插件名|序号> <预设名>",
                "10. 插件配置预设列表 <插件名|序号>",
                "11. 插件配置预设应用 <插件名|序号> <预设名>",
                "12. 插件配置预设删除 <插件名|序号> <预设名>",
                "",
                "所有命令输出默认渲染为图片。",
                "插件列表中的序号可直接代替插件名；查看图中的配置项序号支持层级写法，如 2.1、4.2。",
                "查看命令会输出配置表格图片，展示路径 Key(点号路径) 与 Value。",
                "配置预设用于保存并快捷切换某个插件的整份配置。",
                "键路径支持点号访问，例如：server.port、providers.0.model",
                "设置值会优先按 JSON 解析；解析失败时按普通字符串写入。",
            ]
        )
        yield await self._message_result(
            event,
            message,
            title="插件配置帮助",
            subtitle="AstrBot Plugin Config Manager",
            filename_prefix="help",
        )

    @filter.command("插件配置列表", alias={"plugin-config-list", "pconf-list"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_configs(self, event: AstrMessageEvent):
        """列出当前可管理的插件配置文件。"""
        try:
            config_dir = self._get_config_dir()
            if not config_dir.exists():
                yield await self._error_result(event, f"配置目录不存在：{config_dir}")
                return

            config_items = self._list_plugin_configs()
            if not config_items:
                yield await self._error_result(event, f"未在 {config_dir} 中发现插件配置文件。")
                return

            lines = [f"配置目录：{config_dir}", "可管理插件："]
            for index, (plugin_name, _path) in enumerate(config_items, start=1):
                lines.append(f"{index}. {plugin_name}")
            lines.append("")
            lines.append("提示：后续命令可直接使用插件序号代替插件名。")
            yield await self._message_result(
                event,
                "\n".join(lines),
                title="插件配置列表",
                subtitle=f"共 {len(config_items)} 个配置文件",
                filename_prefix="list",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置查看", alias={"plugin-config-view", "pconf-view"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def view_config(self, event: AstrMessageEvent, plugin_name: str):
        """查看指定插件配置并渲染为图片。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            config_path = self._get_plugin_config_path(resolved_plugin_name)
            config_data = await self._load_json(config_path)
            entries = self._flatten_config_entries(config_data)
            if not entries:
                entries = [
                    ConfigEntry(
                        serial_no="1",
                        key_name="<root>",
                        dot_path="<root>",
                        value_text=self._render_json(config_data),
                        depth=0,
                    )
                ]
            render_path = await self.renderer.render_config_table(
                plugin_name=resolved_plugin_name,
                config_path=config_path,
                entries=entries,
            )
            self._schedule_render_cleanup(render_path)
            yield event.image_result(str(render_path))
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

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
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            config_path = self._get_plugin_config_path(resolved_plugin_name)
            config_data = await self._load_json(config_path)
            resolved_key_path = self._resolve_key_path(config_data, key_path)
            value = self._get_by_path(config_data, resolved_key_path)
            yield await self._message_result(
                event,
                self._render_json(value),
                title=f"配置获取：{resolved_plugin_name}",
                subtitle=f"Key: {'.'.join(map(str, resolved_key_path))}",
                filename_prefix="get",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

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
            resolved_plugin_name = self._resolve_plugin_name(plugin_name, allow_missing=True)
            config_path = self._get_plugin_config_path(resolved_plugin_name, allow_missing=True)
            config_data = await self._load_json(config_path, allow_missing=True)
            parsed_value = self._parse_input_value(value)
            if config_path.exists():
                await self._create_backup(resolved_plugin_name, config_path)
            resolved_key_path = self._resolve_key_path(config_data, key_path, allow_create=True)
            self._set_by_path(config_data, resolved_key_path, parsed_value)
            await self._save_json(config_path, config_data)
            logger.info(f"updated config for {resolved_plugin_name}: {resolved_key_path}")
            yield await self._message_result(
                event,
                f"已写入 {resolved_plugin_name}.{'.'.join(map(str, resolved_key_path))}\n\n值：{self._stringify_value(parsed_value)}",
                title="配置写入成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="set",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

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
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            config_path = self._get_plugin_config_path(resolved_plugin_name)
            config_data = await self._load_json(config_path)
            await self._create_backup(resolved_plugin_name, config_path)
            resolved_key_path = self._resolve_key_path(config_data, key_path)
            self._delete_by_path(config_data, resolved_key_path)
            await self._save_json(config_path, config_data)
            logger.info(f"deleted config value for {resolved_plugin_name}: {resolved_key_path}")
            yield await self._message_result(
                event,
                f"已删除 {resolved_plugin_name}.{'.'.join(map(str, resolved_key_path))}",
                title="配置删除成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="delete",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置备份", alias={"plugin-config-backup", "pconf-backup"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def backup_config(self, event: AstrMessageEvent, plugin_name: str):
        """为指定插件配置创建备份。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            config_path = self._get_plugin_config_path(resolved_plugin_name)
            backup_path = await self._create_backup(resolved_plugin_name, config_path)
            yield await self._message_result(
                event,
                f"已创建备份：{backup_path.name}",
                title="配置备份成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="backup",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command(
        "插件配置备份列表",
        alias={"plugin-config-backup-list", "pconf-backup-list"},
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_backups(self, event: AstrMessageEvent, plugin_name: str):
        """列出指定插件的可用备份。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            backup_dir = self._get_backup_dir(resolved_plugin_name)
            if not backup_dir.exists():
                yield await self._error_result(event, f"{resolved_plugin_name} 暂无备份。")
                return

            backups = sorted(backup_dir.glob("*.json"), reverse=True)
            if not backups:
                yield await self._error_result(event, f"{resolved_plugin_name} 暂无备份。")
                return

            lines = [f"{resolved_plugin_name} 的备份列表："]
            for backup in backups:
                lines.append(f"- {backup.name}")
            yield await self._message_result(
                event,
                "\n".join(lines),
                title="备份列表",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="backup-list",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

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
            resolved_plugin_name = self._resolve_plugin_name(plugin_name, allow_missing=True)
            backup_path = self._get_backup_path(resolved_plugin_name, backup_name)
            if not backup_path.exists():
                raise FileNotFoundError(f"备份不存在：{backup_name}")

            config_path = self._get_plugin_config_path(resolved_plugin_name, allow_missing=True)
            if config_path.exists():
                await self._create_backup(resolved_plugin_name, config_path)
            restored_data = await self._load_json(backup_path)
            await self._save_json(config_path, restored_data)
            logger.info(f"restored config for {resolved_plugin_name} from {backup_name}")
            yield await self._message_result(
                event,
                f"已恢复 {resolved_plugin_name}\n来源备份：{backup_name}",
                title="配置恢复成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="restore",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置预设保存", alias={"plugin-config-preset-save", "pconf-preset-save"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def save_preset(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        preset_name: str,
    ):
        """保存插件配置为预设。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            config_path = self._get_plugin_config_path(resolved_plugin_name)
            config_data = await self._load_json(config_path)
            preset_path = self._get_preset_path(resolved_plugin_name, preset_name)
            await self._save_json(preset_path, config_data)
            yield await self._message_result(
                event,
                f"已保存预设：{preset_name}\n来源插件：{resolved_plugin_name}",
                title="配置预设保存成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="preset-save",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置预设列表", alias={"plugin-config-preset-list", "pconf-preset-list"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_presets(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
    ):
        """列出插件配置预设。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name)
            preset_dir = self._get_preset_dir(resolved_plugin_name)
            if not preset_dir.exists():
                yield await self._error_result(event, f"{resolved_plugin_name} 暂无配置预设。")
                return

            preset_files = sorted(preset_dir.glob("*.json"))
            if not preset_files:
                yield await self._error_result(event, f"{resolved_plugin_name} 暂无配置预设。")
                return

            lines = [f"{resolved_plugin_name} 的配置预设："]
            for preset_file in preset_files:
                lines.append(f"- {preset_file.stem}")
            yield await self._message_result(
                event,
                "\n".join(lines),
                title="配置预设列表",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="preset-list",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置预设应用", alias={"plugin-config-preset-apply", "pconf-preset-apply"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def apply_preset(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        preset_name: str,
    ):
        """应用指定配置预设。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name, allow_missing=True)
            preset_path = self._get_preset_path(resolved_plugin_name, preset_name)
            if not preset_path.exists():
                raise FileNotFoundError(f"预设不存在：{preset_name}")

            config_path = self._get_plugin_config_path(resolved_plugin_name, allow_missing=True)
            if config_path.exists():
                await self._create_backup(resolved_plugin_name, config_path)

            preset_data = await self._load_json(preset_path)
            await self._save_json(config_path, preset_data)
            logger.info(f"applied preset for {resolved_plugin_name}: {preset_name}")
            yield await self._message_result(
                event,
                f"已应用预设：{preset_name}\n目标插件：{resolved_plugin_name}",
                title="配置预设应用成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="preset-apply",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    @filter.command("插件配置预设删除", alias={"plugin-config-preset-delete", "pconf-preset-delete"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_preset(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        preset_name: str,
    ):
        """删除指定配置预设。"""
        try:
            resolved_plugin_name = self._resolve_plugin_name(plugin_name, allow_missing=True)
            preset_path = self._get_preset_path(resolved_plugin_name, preset_name)
            if not preset_path.exists():
                raise FileNotFoundError(f"预设不存在：{preset_name}")

            await asyncio.to_thread(preset_path.unlink)
            logger.info(f"deleted preset for {resolved_plugin_name}: {preset_name}")
            yield await self._message_result(
                event,
                f"已删除预设：{preset_name}\n目标插件：{resolved_plugin_name}",
                title="配置预设删除成功",
                subtitle=f"Plugin: {resolved_plugin_name}",
                filename_prefix="preset-delete",
            )
        except Exception as exc:
            yield await self._error_result(event, self._handle_unexpected_error(exc))

    async def terminate(self):
        """插件卸载时调用。"""

    def _get_config_dir(self) -> Path:
        override = str(self._get_raw_config_value("config_dir_override", "")).strip()
        if override:
            return Path(override).expanduser().resolve()
        return self.data_dir.parent.parent / "config"

    def _list_plugin_configs(self) -> list[tuple[str, Path]]:
        config_dir = self._get_config_dir()
        items: list[tuple[str, Path]] = []
        for path in sorted(config_dir.glob("*_config.json")):
            if not path.is_file():
                continue
            plugin_name = path.name[: -len("_config.json")]
            items.append((plugin_name, path))
        return items

    def _resolve_plugin_name(self, plugin_name: str, allow_missing: bool = False) -> str:
        candidate = plugin_name.strip()
        if not candidate:
            raise ConfigPathError("插件名或插件序号不能为空。")

        if candidate.isdigit():
            plugin_index = int(candidate)
            config_items = self._list_plugin_configs()
            if 1 <= plugin_index <= len(config_items):
                return config_items[plugin_index - 1][0]

            raise ConfigPathError(f"插件序号不存在：{plugin_index}")

        return self._sanitize_plugin_name(candidate)

    def _get_backup_dir(self, plugin_name: str) -> Path:
        return self.data_dir / "backups" / self._sanitize_plugin_name(plugin_name)

    def _get_preset_dir(self, plugin_name: str) -> Path:
        return self.data_dir / "presets" / self._sanitize_plugin_name(plugin_name)

    def _get_backup_path(self, plugin_name: str, backup_name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", backup_name):
            raise ConfigPathError("备份文件名非法。")
        backup_dir = self._get_backup_dir(plugin_name).resolve()
        backup_path = (backup_dir / backup_name).resolve()
        if backup_path.parent != backup_dir:
            raise ConfigPathError("备份文件路径越界。")
        return backup_path

    def _get_preset_path(self, plugin_name: str, preset_name: str) -> Path:
        safe_preset_name = self._sanitize_preset_name(preset_name)
        preset_dir = self._get_preset_dir(plugin_name).resolve()
        preset_path = (preset_dir / f"{safe_preset_name}.json").resolve()
        if preset_path.parent != preset_dir:
            raise ConfigPathError("预设文件路径越界。")
        return preset_path

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

    def _sanitize_preset_name(self, preset_name: str) -> str:
        candidate = preset_name.strip()
        if not candidate:
            raise ConfigPathError("预设名不能为空。")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", candidate):
            raise ConfigPathError("预设名仅允许字母、数字、点、下划线和中划线。")
        return candidate

    def _parse_key_path(self, key_path: str) -> list[str]:
        raw_parts = [part.strip() for part in key_path.split(".")]
        if not raw_parts or any(part == "" for part in raw_parts):
            raise ConfigPathError("键路径不能为空，且不能包含空段。")
        return raw_parts

    def _resolve_key_path(
        self,
        data: dict[str, Any],
        key_path: str,
        allow_create: bool = False,
    ) -> list[str | int]:
        candidate = key_path.strip()
        if not candidate:
            raise ConfigPathError("键路径或配置项序号不能为空。")

        if re.fullmatch(r"\d+(?:\.\d+)*", candidate):
            serial_no = candidate
            entry = self._find_config_entry_by_serial(data, serial_no)
            if entry is not None:
                if entry.dot_path == "<root>":
                    raise ConfigPathError("根节点不支持通过序号直接操作。")
                return self._resolve_dot_path(data, entry.dot_path, allow_create=False)
            if not allow_create:
                raise ConfigPathError(f"配置项序号不存在：{serial_no}")

        return self._resolve_dot_path(data, candidate, allow_create=allow_create)

    def _resolve_dot_path(
        self,
        data: Any,
        key_path: str,
        allow_create: bool,
    ) -> list[str | int]:
        raw_parts = self._parse_key_path(key_path)
        resolved_parts: list[str | int] = []
        current = data

        for index, part in enumerate(raw_parts):
            is_last = index == len(raw_parts) - 1
            next_part = raw_parts[index + 1] if not is_last else None

            if not isinstance(current, (dict, list)):
                if not allow_create:
                    raise ConfigPathError(f"路径段 {part} 的父节点不是对象或列表。")
                current = [] if part.isdigit() else {}

            if isinstance(current, list):
                if not part.isdigit():
                    raise ConfigPathError(f"路径段 {part} 不是列表索引。")
                list_index = int(part)
                resolved_parts.append(list_index)
                if is_last:
                    continue
                if list_index >= len(current):
                    if not allow_create:
                        raise ConfigPathError(f"列表索引越界：{list_index}")
                    current = [] if (next_part and next_part.isdigit()) else {}
                    continue
                current = current[list_index]
                continue

            resolved_parts.append(part)
            if is_last:
                continue
            if part not in current:
                if not allow_create:
                    raise ConfigPathError(f"键不存在：{part}")
                current = [] if (next_part and next_part.isdigit()) else {}
                continue
            current = current[part]

        return resolved_parts

    def _find_config_entry_by_serial(self, data: dict[str, Any], serial_no: str) -> ConfigEntry | None:
        serial_parts = serial_no.split(".")
        if any((not part.isdigit()) or int(part) <= 0 for part in serial_parts):
            raise ConfigPathError("配置项序号必须为大于 0 的层级序号，例如 1、2.1、4.2。")
        for entry in self._flatten_config_entries(data):
            if entry.serial_no == serial_no:
                return entry
        return None

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

    def _flatten_config_entries(self, data: Any) -> list[ConfigEntry]:
        entries: list[ConfigEntry] = []

        def append_entry(path_parts: list[str], serial_parts: list[int], value_text: str):
            dot_path = ".".join(path_parts) if path_parts else "<root>"
            key_name = path_parts[-1] if path_parts else "<root>"
            entries.append(
                ConfigEntry(
                    serial_no=".".join(str(part) for part in serial_parts),
                    key_name=key_name,
                    dot_path=dot_path,
                    value_text=value_text,
                    depth=max(0, len(path_parts) - 1),
                )
            )

        def visit(node: Any, path_parts: list[str], serial_parts: list[int]):
            if isinstance(node, dict):
                if path_parts:
                    append_entry(path_parts, serial_parts, self._summarize_node(node))
                for index, (key, value) in enumerate(node.items(), start=1):
                    visit(value, [*path_parts, str(key)], [*serial_parts, index])
                return

            if isinstance(node, list):
                if path_parts:
                    append_entry(path_parts, serial_parts, self._summarize_node(node))
                for index, value in enumerate(node):
                    visit(value, [*path_parts, str(index)], [*serial_parts, index + 1])
                return

            if not path_parts:
                append_entry([], [1], self._stringify_value(node))
                return

            append_entry(path_parts, serial_parts, self._stringify_value(node))

        if isinstance(data, dict):
            for index, (key, value) in enumerate(data.items(), start=1):
                visit(value, [str(key)], [index])
            return entries

        if isinstance(data, list):
            for index, value in enumerate(data, start=1):
                visit(value, [str(index - 1)], [index])
            return entries

        visit(data, [], [])
        return entries

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _summarize_node(self, value: Any) -> str:
        if isinstance(value, dict):
            return f"对象 ({len(value)} 项)"
        if isinstance(value, list):
            return f"列表 ({len(value)} 项)"
        return self._stringify_value(value)

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

    async def _message_result(
        self,
        event: AstrMessageEvent,
        message: str,
        title: str,
        subtitle: str = "",
        filename_prefix: str = "message",
    ):
        try:
            render_path = await self.renderer.render_text_card(
                title=title,
                message=message,
                subtitle=subtitle,
                filename_prefix=filename_prefix,
            )
            self._schedule_render_cleanup(render_path)
            return event.image_result(str(render_path))
        except Exception as exc:
            logger.error(f"render message image failed: {exc}")
            return event.plain_result(message)

    async def _error_result(self, event: AstrMessageEvent, message: str):
        return await self._message_result(
            event,
            message,
            title="操作失败",
            subtitle="Plugin Config Manager",
            filename_prefix="error",
        )

    def _schedule_render_cleanup(self, render_path: Path):
        asyncio.create_task(self._delete_render_file_later(render_path))

    async def _delete_render_file_later(self, render_path: Path):
        try:
            await asyncio.sleep(120)
            render_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(f"cleanup rendered image failed: {exc}")

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
            with path.open("r", encoding="utf-8-sig") as file:
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
