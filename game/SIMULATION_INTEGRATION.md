# 校园客户端与模拟服务

## 打开与操作

在 Godot 4.7.2 中导入本目录的 `project.godot`，运行项目（F5）。默认进入七图校园，Godot 自动启动本机 Python 校园服务。Windows 需要 `python` 命令，macOS 需要 `python3`；当前验证环境为 macOS，Windows 发行验收尚未完成。

- WASD 移动；走到区域连接边缘或建筑入口切换场景。
- T 打开手机，可查看论坛、联系人、社团、队伍、商城、交易、健康和存档等功能。
- M 打开校园地图；NPC 查看与日志使用校园人物面板，不再使用旧城镇完整人口列表。
- 没有其他面板时，Esc 打开通用接口设置；也可由手机进入。关闭后恢复打开前的暂停状态。

场景中的 NPC 是校园权威状态的表现层，路线来自校园行动执行；不再按旧城镇的场景坐标重新生成第二套人口。

## 通用 LLM 接口

支持离线规则、OpenAI 兼容接口和 Ollama。填入服务方的地址、模型名和个人密钥，选择“保存并应用”。启动默认离线，应用配置本身不发送模型请求；真实聊天或 NPC 认知触发时才调用。

玩家主动聊天没有新增每日/每时段次数上限。后台 NPC 自动决策仍有现有可配置预算、超时和规则回退；这不是玩家聊天次数配额。本批不改变认知策略，也不进行付费测试。

配置默认保存在 `user://llm_interfaces.cfg`。输入框遮挡密钥，但本机配置文件未加密；不要提交、共享或录屏展示密钥。为保持旧配置及校园存档的位置，Godot 工程内部用户数据标识暂不改名。

## 校园服务契约

自动启动脚本为 `tools/simulation/godot_simulation_server.py`，默认只监听 `127.0.0.1:8765`。

- `GET /health`：校园服务健康检查。
- `GET /kernel/campus-snapshot`：校园视图，也是客户端启动握手。
- `POST /kernel/command`：统一校园行动，覆盖移动、时段、任务、社交、物品、交易和卡牌等已实现操作。
- `GET /kernel/npcs/{id}/chronicle`：NPC 日志分页。
- `POST /kernel/saves`：校园存档操作。
- `POST /configure`：配置通用认知接口。

旧城镇 `/snapshot`、`/step`、`/trade`、`/use-item`、`/action` 返回 410。Godot 不再声明这些旧请求方法、旧快照或旧结果信号。校园库存和私人交易仍走统一校园行动，不受旧界面删除影响。

校园七张美术地图由 `data/campus_art_catalog.json` 描述；教学区、生活区和室内入口的语义连接由校园内容与导航系统负责。旧廷根图、蓝图生成器、旧场景区域映射及旧人口/交易 UI 已退役。

## 存档与测试隔离

玩家槽默认在 `user://campus_saves`。本批不修改校园内容版本、状态 Schema 或保存位置。

开发验收可指定：

- `GODOT_SIM_PORT`：独立测试端口。
- `GODOT_SIM_SAVE_DIR`：独立测试存档目录。
- `GODOT_SIM_SETTINGS_PATH`：独立测试接口配置文件。
- `GODOT_SIM_EXTERNAL_SERVER=1`：使用明确启动的验收服务，不另起子进程。

Godot 验收脚本位于 `tools/test_campus_*.gd`，在仓库根目录运行 Python 全局测试。每批结果和已知边界记入 `production/VERIFICATION.md`；不要把测试夹具预置的人物位置或伤势当作自然涌现证据。
