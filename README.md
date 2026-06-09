# astrbot_plugin_config_manager

一个用于在聊天中统一管理其他 AstrBot 插件配置文件的插件。

## 功能

- 自动定位 AstrBot 的 `data/config` 目录
- 列出已发现的插件配置文件
- 将配置内容渲染为表格图片
- 查看时按 `键名 / 点号路径 / 值` 展示每一项配置
- 支持按点号路径读取配置，例如 `providers.0.model`
- 支持写入和删除配置项
- 在修改前自动创建备份
- 支持列出备份并按备份文件名恢复

## 命令

- `插件配置帮助`
- `插件配置列表`
- `插件配置查看 <插件名>`
- `插件配置获取 <插件名> <键路径>`
- `插件配置设置 <插件名> <键路径> <值>`
- `插件配置删除 <插件名> <键路径>`
- `插件配置备份 <插件名>`
- `插件配置备份列表 <插件名>`
- `插件配置恢复 <插件名> <备份文件名>`

## 示例

```text
插件配置列表
插件配置查看 astrbot_plugin_example
插件配置获取 astrbot_plugin_example server.port
插件配置设置 astrbot_plugin_example server.port 8080
插件配置设置 astrbot_plugin_example providers.0.model "gpt-4.1"
插件配置删除 astrbot_plugin_example providers.0.api_key
插件配置备份 astrbot_plugin_example
插件配置备份列表 astrbot_plugin_example
插件配置恢复 astrbot_plugin_example 20260609_120000.json
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
- 备份文件保存在 `data/plugin_data/astrbot_plugin_config_manager/backups/`
- 渲染后的图片保存在 `data/plugin_data/astrbot_plugin_config_manager/rendered_configs/`
- 如果实际仓库地址与 `metadata.yaml` 中的 `repo` 不一致，发布前请改成真实地址
