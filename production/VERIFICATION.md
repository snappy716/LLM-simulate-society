# 重构验证清单

- 旧版测试：`cd emergent_town_demo && python3 -m unittest discover -s tests -v`
- 新版测试：`python3 -m unittest discover -s tests -v`
- 校园架构专项：`python3 -m unittest tests.test_campus_demo_architecture -v`
- 程序底座专项：`python3 -m unittest tests.test_world_kernel tests.test_content_registry tests.test_kernel_persistence tests.test_kernel_api_contracts -v`
- 校园地点与人口专项：`python3 -m unittest tests.test_campus_locations tests.test_campus_population tests.test_campus_kernel_bridge tests.test_godot_campus_navigation -v`
- 四时段与主要行动专项：`python3 -m unittest tests.test_action_economy tests.test_campus_locations tests.test_campus_kernel_bridge tests.test_kernel_api_contracts -v`
- 校园日程与容量专项：`python3 -m unittest tests.test_campus_schedules tests.test_campus_population tests.test_campus_kernel_bridge tests.test_content_registry -v`
- NPC 寻路与活动专项：`python3 -m unittest tests.test_campus_activities tests.test_campus_locations tests.test_campus_kernel_bridge tests.test_godot_campus_navigation -v`
- 校园活动效果专项：`python3 -m unittest tests.test_campus_activity_effects tests.test_campus_activities tests.test_campus_kernel_bridge tests.test_content_registry -v`
- Python 编译：`python3 -m compileall -q simulation tests`
- 补丁格式：`git diff --check`
- 离线启动：`python3 -m simulation --days 0 --llm rule --quiet`
- API 冒烟：实例化 `simulation.api.server.SimulationBridge` 并验证快照。
- 交易冒烟：验证 `/trade` 买卖、资金/库存原子更新和失败不变性。
- 统一行动冒烟：验证 `/action` 的丢弃→拾取、装备→卸下，以及
  `performed=true / ok=false` 的有效检定失败。
- Godot 4.7 导入：`Godot --headless --editor --path game --quit`
- Godot 校园导航端到端：`Godot --headless --path game --script res://tools/test_campus_navigation_flow.gd`，必须输出 `CAMPUS_NAVIGATION_FLOW_OK`。
- Godot 协作美术联调：`Godot --headless --path game --script res://tools/test_campus_collab_flow.gd`，必须输出 `CAMPUS_COLLAB_FLOW_OK`；图形渲染可运行 `res://tools/capture_campus_collab.gd`。
- 校园美术完整性：`campus_art_catalog.json` 必须有 20 个唯一条目，每个 PNG 文件存在且 IHDR 尺寸与目录一致；地图跨区必须走 `FAST_TRAVEL_CAMPUS`，不得直接修改地点。
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

NPC 统一寻路与活动执行阶段验收：当前工程 224 项、旧版工程 46 项测试通过；固定种子 42
连续运行 7 天、28 个时段，共执行 5,600 个 NPC 计划，发生 4,303 人次跨地点移动并通过
20,777 个合法通道，完成 3,925 次主要活动和 1,675 次自由活动，路径、权限或排班阻塞为 0。
玩家不会被日程自动接管，移动仍免费；NPC 与玩家复用同一个通行处理器，到达后才结算活动与
个人行动次数。校园快照升级到 v4，保留可按需查询的活动依据。Godot 4.7.2 导入、组件、
旧主场景和校园端到端测试均通过；校园灰盒只回放当前画面附近最多 18 名 NPC 的真实通勤
轨迹，进入室内后退场，默认不显示 NPC 名称或活动状态文字。

校园活动真实结算阶段验收：当前工程 232 项、旧版工程 46 项测试通过；现有日程引用的 32 项
活动全部拥有数据驱动效果，玩家与 NPC 共用同一处理器和主要行动预算。固定种子 42 连续运行
7 天、28 个时段，共结算 5,600 次活动效果、20,777 段合法移动、1,167 次免费用餐和 224 次
免费短社交；每名 NPC 恰好结算 28 个计划，饥饿需求保持在 23～68，动态状态和知识不变量错误
为 0。Godot 校园快照升级到 v5；Godot 4.7.2 导入、组件、校园端到端、旧主场景以及实际图形
窗口启动均通过。桥接端口默认仍为 8765，测试或冲突环境可使用 `GODOT_SIM_PORT` 指定独立端口。

校园协作美术首次接入验收：从 `Project-c-0.1.rar` 的 20 张地图迭代图中只保留 5 张地点候选，
没有导入 `.godot/`、`.import`、历史迭代稿或会绕过内核的硬编码传送与随机游走实现。新增独立
美术联调场景，使用场景语义锚点回放权威 NPC 路线，并验证道路连续跨区、进入共享大厅、返回
同一美术场景、时段推进及晚间 NPC 可见移动。当前工程 232 项、旧版工程 46 项、原校园导航
端到端和协作美术端到端均通过；Godot 4.7.2 图形渲染确认玩家位于主道路。该场景不替换正式
入口，地图在补齐授权并去除真实校名和现实品牌前仅供开发联调。

校园协作包完整接入验收：`Project-c-0.1.rar` 中的 20 张校园 PNG 已全部加入可浏览目录，保留首次
接入的 5 张稳定别名以兼容历史场景。校园联调场景现已接入完整地图选择、Python 内核权威免费传送、
现有模块化玩家与 NPC、WASD 移动、动态镜头边界、1×/2×/3×缩放、上下边缘浏览和手机 UI 原型。
端到端测试会实际切换 2040 像素与 3548 像素宽地图，验证人物模块、手机暂停、道路与室内通行、
NPC 通勤，以及地图传送不推进分钟、不消耗主要行动。协作包的随机游走 NPC、硬编码传送、重复角色
脚本和缓存未接入，因为它们会与现有权威模拟冲突。当前工程 238 项、旧版工程 46 项测试通过；
Godot 4.7.2 编辑器导入、组件、原校园导航、完整协作场景端到端和旧主场景启动全部通过。图形渲染
已分别检查默认校园场景、20 图滚动目录与手机校园相册页面。

本轮固定种子 42 的 14 天结果：共 16,385 个事件，497 笔商店成交、264 笔私人成交、
236 次统一物品使用；普通重复交易者平均间隔 3.71 天、最短 2 天且同日重复为 0；
职业交易者均未超过职业每日额度。经济、物品实例与装备不变量检查均为 0 错误。
种子长期仪式受世界内官方干预而在准备场地阶段失败，并非材料阻塞；同期产生 9 次
`RITUAL_BLOCKED_MISSING_MATERIAL`，证明无材料的临时仪式会被显式阻断。
