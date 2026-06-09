# astrbot_plugin_config_manager

一个用于在聊天中统一管理其他 AstrBot 插件配置文件的插件。

## 功能

- 自动定位 AstrBot 的 `data/config` 目录
- 列出已发现的插件配置文件，并为插件分配稳定序号
- 将配置内容渲染为表格图片
- 查看时按 `序号 / Key(点号路径) / Value` 展示每一项配置
- 支持直接使用插件序号代替插件名
- 支持直接使用配置项层级序号代替键路径，例如 `2.1`、`4.2`
- 支持按点号路径读取配置，例如 `providers.0.model`
- 支持写入和删除配置项
- 在修改前自动创建备份
- 支持列出备份并按备份文件名恢复
- 支持保存、列出、应用、删除配置预设

## 命令

- `插件配置帮助`
- `插件配置列表`
- `插件配置查看 <插件名|序号>`
- `插件配置获取 <插件名|序号> <键路径|序号>`
- `插件配置设置 <插件名|序号> <键路径|序号> <值>`
- `插件配置删除 <插件名|序号> <键路径|序号>`
- `插件配置备份 <插件名|序号>`
- `插件配置备份列表 <插件名|序号>`
- `插件配置恢复 <插件名|序号> <备份文件名>`
- `插件配置预设保存 <插件名|序号> <预设名>`
- `插件配置预设列表 <插件名|序号>`
- `插件配置预设应用 <插件名|序号> <预设名>`
- `插件配置预设删除 <插件名|序号> <预设名>`

## 示例

```text
插件配置列表
插件配置查看 astrbot_plugin_example
插件配置查看 1
插件配置获取 astrbot_plugin_example server.port
插件配置获取 1 1.2
插件配置设置 astrbot_plugin_example server.port 8080
插件配置设置 astrbot_plugin_example providers.0.model "gpt-4.1"
插件配置设置 1 2.1.2 "https://example.com/v2"
插件配置删除 astrbot_plugin_example providers.0.api_key
插件配置备份 astrbot_plugin_example
插件配置备份列表 astrbot_plugin_example
插件配置恢复 astrbot_plugin_example 20260609_120000.json
插件配置预设保存 astrbot_plugin_example office_mode
插件配置预设列表 astrbot_plugin_example
插件配置预设应用 astrbot_plugin_example office_mode
插件配置预设删除 astrbot_plugin_example office_mode
```

## WebUI 配置项

- `config_dir_override`：覆盖自动检测到的配置目录
- `backup_keep_count`：每个插件保留的备份数量
- `image_width`：生成图片的宽度
- `image_max_rows`：单张图片最多渲染多少行配置
- `render_image_keep_count`：保留多少张历史渲染图片
- `font_path`：自定义字体文件路径，用于处理默认字体无法正确显示的情况

## 依赖

- `Pillow`

## 说明

- 所有命令仅管理员可用
- 插件列表中的序号可用于后续所有插件级命令
- 查看图片中的配置项层级序号可用于 `获取 / 设置 / 删除`，例如 `2.1`、`4.1`、`4.2`
- 备份文件保存在 `data/plugin_data/astrbot_plugin_config_manager/backups/`
- 配置预设保存在 `data/plugin_data/astrbot_plugin_config_manager/presets/`
- 渲染后的图片保存在 `data/plugin_data/astrbot_plugin_config_manager/rendered_configs/`
- 如果实际仓库地址与 `metadata.yaml` 中的 `repo` 不一致，发布前请改成真实地址
