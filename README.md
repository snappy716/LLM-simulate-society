# Project A · 校园社会模拟 Demo

当前开发入口：`game/project.godot`。运行项目直接进入校园，生产服务只创建一个校园世界，不再同时运行旧城镇。

校园内容现独立加载 9 种校园物品及既有校园系统。已知旧校园内容版本可严格迁移，读取不会覆盖原档；任意其他内容版本和旧城镇人物档不自动转换。

执行顺序见 [实施路线](design/IMPLEMENTATION_ROADMAP.md)；当前正在按 [旧城镇下线清单](design/LEGACY_RETIREMENT.md) 清理剩余依赖，完成后继续 UI 统一。Demo 尚未整体完成。

## 已可测试的内容

- 七张校园地图、区域/入口通行、玩家移动和镜头、模块化人物、可见 NPC 行走与人物日志。
- 200 名持久 NPC、课程/社团日程、关系互动、双层论坛、任务竞争、手机联系人和对话、行动小队。
- 校园唯一钱包和库存、文字商店、物品转交/使用/装备、自主采购、私人报价和结算、商店付费次日补货。
- 人物牌三排部署、抽弃牌、共享费用、出牌与基础效果；跨场生命/专注保留，战斗间治疗，表世界充分休息全部恢复。
- 三个手动存档槽、覆盖备份和完整校园检查点恢复；通用 OpenAI 兼容接口、本地 Ollama、离线规则模式。

完整敌方回合、调查与证据、知识成长、长期多步 LLM 计划、持续局势和四阶段主线仍需实现。当前规则模拟和局部 LLM 互动不能等同于已经实现无限自由的自主社会。

## 启动与操作

1. 保持 `game/`、`simulation/`、`content/` 为同一仓库下的兄弟目录。
2. 安装 Godot 4.7 系列及可从 PATH 调用的 Python；Windows 使用 `python`，macOS/Linux 使用 `python3`。
3. 在 Godot 导入 `game/project.godot`，运行项目（F5），无需先打开旧城镇场景。
4. 按 T 打开手机，可访问存读档、接口设置、商城、交易、日志相关人物功能、社团、小队与论坛。

| 操作 | 入口 |
| --- | --- |
| 移动 | WASD / 方向键 |
| 校园地图 | M |
| 手机 | T |
| 附近 NPC 交互 | E；点击人物查看信息 |
| API 设置 | 手机“接口设置”；无其他面板时 Esc |
| 存读档 | 手机“存读档” |
| 推进时段 | 场景中的“结束当前时段” |

上午、下午、晚上、凌晨四时段不变。聊天、购物、吃饭和普通移动不消耗主要行动。普通休息与回满资源的充分休息仍按已有规则区分。

## LLM 与存档

启动默认离线，不因本地旧配置或环境里存在 API Key 就自动启用模型。玩家在接口设置中填写 Base URL、模型名和自己的 Key，保存并应用后，校园对话和 NPC 决策才会使用该提供器。应用配置本身不调用模型；开发测试不消耗付费 API。玩家聊天不增加硬次数上限。

接口配置保存在本机 `user://llm_interfaces.cfg`；手动存档位于 `user://campus_saves`，不包含 API Key。本次保留原 `config/name="project-a-0.2"` 作为用户数据路径兼容标识，避免改变名称后找不到既有配置和存档；它不表示仍启动旧城镇。

读档使用现有区域安全落点，不保存精确像素站位。只支持已知的有限校园迁移，未知旧档拒绝强行转换，详见 [存读档边界](design/CAMPUS_SAVE_RUNTIME.md)。

## 服务与验证

通常 Godot 自动启动本地服务；手动启动可在仓库根目录运行：

```sh
python3 -m simulation --port 8765
```

Windows 将 `python3` 换成 `python`。服务已手动启动时，为 Godot 设置 `GODOT_SIM_EXTERNAL_SERVER=1`，端口可由 `GODOT_SIM_PORT` 指定。

正式接口包括 `/health`、`/configure`、`/kernel/campus-snapshot`、`/kernel/command`、`/kernel/saves` 与人物日志。旧城镇的 `/snapshot`、`/step`、`/trade`、`/use-item`、`/action` 返回 410，不自动转译为校园操作。

```sh
python3 -m unittest discover -s tests -v
python3 -m tests.run_campus_trade_soak --days 7 --seed 42
```

Godot 启动验收脚本：`game/tools/test_campus_startup_flow.gd`。测试时用独立 `GODOT_SIM_PORT`、`GODOT_SIM_SAVE_DIR` 及 `GODOT_SIM_SETTINGS_PATH`，不要覆盖自己的存档/接口文件。完整结果见 [验收记录](production/VERIFICATION.md)。Mac 图形测试不替代 Windows 实机发布验收。

## 架构与历史

```text
game/             Godot 场景、输入、UI 与表现
simulation/       权威领域、行动、系统、认知、叙事、存档、API
content/          校园内容与待裁剪的共用数据
contracts/        请求、事件与投影 Schema
tests/            校园测试及剩余显式兼容测试
design/           世界观、架构和执行路线
production/       验证与发布记录
```

旧独立目录 `emergent_town_demo/`、`project-a-0.2/` 和原 ZIP 已删除，可从 Git 历史恢复。旧运行时和旧 Godot 工具尚未全部物理删除；`simulation/api/legacy_bridge.py` 仅供尚未退休的历史功能测试显式导入，不挂载生产 HTTP。七图及校园使用的人物素材继续保留。

- [世界与玩法大纲](design/CAMPUS_WORLD_AND_GAMEPLAY_DESIGN.md)
- [目标架构](design/CAMPUS_DEMO_ARCHITECTURE.md)
- [卡牌战斗框架](design/CARD_COMBAT_FRAMEWORK.md)
- [人物日志](design/NPC_ACTIVITY_LOG_SYSTEM.md)
- [素材来源与许可](game/THIRD_PARTY_ASSETS.md)

开发分支使用 `codex/`，每批测试后提交；不自动合并 main，不把私人配置、API Key、运行数据或截图上传仓库。
