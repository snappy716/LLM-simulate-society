# 重构验证清单

- 旧版测试：`cd emergent_town_demo && python3 -m unittest discover -s tests -v`
- 新版测试：`python3 -m unittest discover -s tests -v`
- 离线启动：`python3 -m simulation --days 0 --llm rule --quiet`
- API 冒烟：实例化 `simulation.api.server.SimulationBridge` 并验证快照。
- 交易冒烟：验证 `/trade` 买卖、资金/库存原子更新和失败不变性。
- Godot 4.7 导入：`Godot --headless --editor --path game --quit`
- Godot 运行：启动 `game/project.godot`，确认后端连接、200 NPC 首个快照与城市地图加载。
- Windows 目标检查：Windows 使用 `python`，macOS/Linux 使用 `python3`；不得提交平台绝对路径。
- 目录保护：确认 `project-a-0.2/`、`emergent_town_demo/` 与原 ZIP 仍存在。
- Godot 文字交易：按 `I` 打开面板，买入黑麦面包并卖出初始麻绳。
