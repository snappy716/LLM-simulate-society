# 重构验证清单

- 旧版测试：`cd emergent_town_demo && python3 -m unittest discover -s tests -v`
- 新版测试：`python3 -m unittest discover -s tests -v`
- 离线启动：`python3 -m simulation --days 0 --llm rule --quiet`
- API 冒烟：实例化 `simulation.api.server.SimulationBridge` 并验证快照。
- 交易冒烟：验证 `/trade` 买卖、资金/库存原子更新和失败不变性。
- 统一行动冒烟：验证 `/action` 的丢弃→拾取、装备→卸下，以及
  `performed=true / ok=false` 的有效检定失败。
- Godot 4.7 导入：`Godot --headless --editor --path game --quit`
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

本轮固定种子 42 的 14 天结果：共 16,385 个事件，497 笔商店成交、264 笔私人成交、
236 次统一物品使用；普通重复交易者平均间隔 3.71 天、最短 2 天且同日重复为 0；
职业交易者均未超过职业每日额度。经济、物品实例与装备不变量检查均为 0 错误。
种子长期仪式受世界内官方干预而在准备场地阶段失败，并非材料阻塞；同期产生 9 次
`RITUAL_BLOCKED_MISSING_MATERIAL`，证明无材料的临时仪式会被显式阻断。
