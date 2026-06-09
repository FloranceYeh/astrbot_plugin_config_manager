# astrbot_plugin_config_manager

一个用于一键管理 AstrBot 其他插件配置文件的插件，面向管理员提供统一的查看、读写、删除、备份与恢复能力。

## 功能

- 自动定位 AstrBot 的 `data/config` 目录
- 列出当前已有的插件配置文件
- 查看任意插件完整配置，并将解析后的 JSON 渲染为图片输出
- 按点号路径读取配置项，如 `providers.0.model`
- 直接写入或删除配置项
- 修改前自动备份
- 按插件列出备份并按文件名恢复

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

- `config_dir_override`：覆盖自动探测到的配置目录
- `backup_keep_count`：每个插件最多保留多少份备份
- `preview_limit`：图片渲染失败时，文本兜底输出的字符上限
- `image_char_limit`：图片渲染前允许的最大字符数

## 说明

- 仅管理员可调用这些命令
- 插件默认只接受安全的插件名字符：字母、数字、点、下划线、中划线
- 运行时备份保存在 `data/plugin_data/astrbot_plugin_config_manager/backups/`
- 如果你的仓库地址与 `metadata.yaml` 中的 `repo` 不一致，发布前请改成真实地址
