# 重构验证清单

- 旧版测试：`cd emergent_town_demo && python3 -m unittest discover -s tests -v`
- 新版测试：`python3 -m unittest discover -s tests -v`
- 校园架构专项：`python3 -m unittest tests.test_campus_demo_architecture -v`
- 程序底座专项：`python3 -m unittest tests.test_world_kernel tests.test_content_registry tests.test_kernel_persistence tests.test_kernel_api_contracts -v`
- 校园地点与人口专项：`python3 -m unittest tests.test_campus_locations tests.test_campus_population tests.test_campus_kernel_bridge tests.test_godot_campus_navigation -v`
- 四时段与主要行动专项：`python3 -m unittest tests.test_action_economy tests.test_campus_locations tests.test_campus_kernel_bridge tests.test_kernel_api_contracts -v`
- 校园日程与容量专项：`python3 -m unittest tests.test_campus_schedules tests.test_campus_population tests.test_campus_kernel_bridge tests.test_content_registry -v`
- Python 编译：`python3 -m compileall -q simulation tests`
- 补丁格式：`git diff --check`
- 离线启动：`python3 -m simulation --days 0 --llm rule --quiet`
- API 冒烟：实例化 `simulation.api.server.SimulationBridge` 并验证快照。
- 交易冒烟：验证 `/trade` 买卖、资金/库存原子更新和失败不变性。
- 统一行动冒烟：验证 `/action` 的丢弃→拾取、装备→卸下，以及
  `performed=true / ok=false` 的有效检定失败。
- Godot 4.7 导入：`Godot --headless --editor --path game --quit`
- Godot 校园导航端到端：`Godot --headless --path game --script res://tools/test_campus_navigation_flow.gd`，必须输出 `CAMPUS_NAVIGATION_FLOW_OK`。
- Godot 运行：启动 `game/project.godot`，确认后端连接、200 NPC 首个快照与城市地图加载。
- Windows 目标检查：Windows 使用 `python`，macOS/Linux 使用 `python3`；不得提交平台绝对路径。
- 目录保护：确认 `project-a-0.2/`、`emergent_town_demo/` 与原 ZIP 仍存在。
- Godot 文字交易：按 `I` 打开面板，买入黑麦面包并卖出初始麻绳。
- Godot 文字物品：按 `I` 打开面板，选择背包中的黑麦面包并点击“使用背包物品”，
  确认数量减少、饱食状态变化和 `ITEM_USED` 事件同步返回。
- Godot 文字装备：按 `I` 打开面板，选择可装备物品进行装备、卸下；选择未装备物品
  丢到当前场景，确认状态文字和快照中的实例位置同步变化。
- 物品机制专项：验证门锁/钥匙/撬棍/绳索、伪装/假证/徽章、笔记本情报衰减、
  武器威慑与证据、合法/秘密仪式的完整配方原子消耗。
- NPC 交易长跑：至少模拟 14 天；普通重复交易者平均间隔必须在 2～4 天且同日重复为 0，
  职业交易者必须能够在每日额度内完成多笔交易。
- 校园系统长跑：逐项接入后先运行 7～14 天，四阶段接入完成后运行完整 28 天；
  检查任务锁、行动次数、NPC 地点、觉醒槽位、夜间参与人数和主线锚点不变量。
- 程序底座检查点：验证校验和、内容版本、随机流续接和读档后的命令幂等。
- 程序底座事件日志：验证重开不截断、事件序号连续、日志失败时世界事务回滚。

第一阶段程序底座验收：当前工程 175 项、旧版工程 46 项测试通过；固定种子 42 的
规则模式 28 天模拟完成；Godot 4.7.2 编辑器导入和主场景连接本地服务均通过。
公共 Godot 快照仍为 v2，内核检查点独立使用 `kernel_checkpoint_version=1`。

校园地点与人口阶段验收：当前工程 204 项、旧版工程 46 项测试通过；Godot 4.7.2
组件实例测试输出 `CAMPUS_COMPONENTS_OK`；导航端到端测试实际完成道路连续跨区、楼梯进楼、
室内出门及返回原楼梯锚点并输出 `CAMPUS_NAVIGATION_FLOW_OK`。主场景与校园导航灰盒均可
无界面启动，并已在 Godot 图形界面检查灰盒构图。校园内核
最初通过独立 `/kernel/campus-snapshot` v1 与 `/kernel/command` 并行接入，未替换旧快照 v2。

四时段与主要行动预算阶段验收：当前工程 214 项、旧版工程 46 项测试通过；固定种子 42
的规则模式 14 天模拟完成；Godot 4.7.2 编辑器导入、组件测试、旧主场景启动以及校园导航和
时段推进端到端均通过。校园快照升级为 v2，加入玩家主要行动余额和规则投影。普通移动保持
免费且不推进分钟；聊天、购物和吃饭也被定义为自由行动。每个角色每时段只有 1 次主要行动，
额度彼此独立并在 `ADVANCE_PHASE` 时统一重置。校园灰盒包含可见调试面板和时段推进按钮；
本阶段仍未启用精细分钟消耗。

校园日程与容量阶段验收：当前工程 220 项、旧版工程 46 项测试通过；固定种子 42 的规则模式
14 天模拟完成；Godot 4.7.2 项目导入及校园端到端通过。201 名角色生成 5628 个一周计划槽位，
默认内容没有非法地点或容量改派；人工制造的 10 人争抢 8 人心理支持室场景能稳定改派 2 人。
校园快照升级到 v3，并在灰盒面板展示随时段变化的玩家计划。计划生成不移动角色、不扣行动，
因此下一阶段仍需实现 NPC 统一寻路与实际活动执行。

本轮固定种子 42 的 14 天结果：共 16,385 个事件，497 笔商店成交、264 笔私人成交、
236 次统一物品使用；普通重复交易者平均间隔 3.71 天、最短 2 天且同日重复为 0；
职业交易者均未超过职业每日额度。经济、物品实例与装备不变量检查均为 0 错误。
种子长期仪式受世界内官方干预而在准备场地阶段失败，并非材料阻塞；同期产生 9 次
`RITUAL_BLOCKED_MISSING_MATERIAL`，证明无材料的临时仪式会被显式阻断。
