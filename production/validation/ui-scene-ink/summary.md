# 场景融合 HUD 验证记录

日期：2026-09-11。基线：9bb0fce。测试平台：macOS，Godot 4.7.2，Python 3.12.14。未调用付费 API。

## 自动回归

- `production/run_godot_checks.py` 的 STANDARD + FIXTURES 共 66 个流程，按列表偶数/奇数索引分为两个互不重叠的 33 项组，独立端口、设置与存档。
- 组一：`campus-godot-checks-go1kgy9h`，退出码 0，`GODOT_CHECKS_OK 33 flows`。
- 组二：`campus-godot-checks-q1a4a2wo`，退出码 0，`GODOT_CHECKS_OK 33 flows`。
- 上述日志保存在系统临时目录，每个流程各有 `godot.log`。两组覆盖启动、移动、地图、存档、物品、战斗、任务、社交、关系、手机、夜间规划等当前注册流程。
- 追加键盘焦点测试首次失败：无显示渲染器不提供 `shader_parameter/emphasis` 的动态属性反射。已改用 `tween_method` 显式写入参数，不依赖动态属性路径；每个按钮保存独立动画值。
- 修复后 HUD 专项：`campus-godot-checks-0ikhwfnk`，退出码 0，`GODOT_CHECKS_OK 1 flows`。包括三分辨率、各入口、空底框、热区、焦点渐亮/恢复、材质独立、消息去重、追踪折叠和真实时段命令。
- Python：`python3 -m unittest tests.test_campus_ui_theme tests.test_godot_resource_integrity tests.test_godot_campus_navigation`，40 项通过。
- 全量 Python 95 模块 / 906 项是基线上一批的结果，本轮未重复全量业务测试。

## 实际渲染

- 使用 `open -g -j -n` 在后台隐藏启动 Godot，OpenGL Compatibility / Apple M5；没有前台抢焦点。
- `capture_campus_minimal_hud.gd` 完成，标记 `CAMPUS_MINIMAL_HUD_CAPTURE_OK`，无脚本或渲染错误。
- 真实材质参数断言：卡牌图标焦点渐亮后 > 0.99，失焦后 < 0.01；另存 `02-hud-focus.png` 对照普通画面。
- 检查七张现有校园图的配色、文字和图标可读性，以及人物、物品、卡牌、关系、时间页面入口。
- 地图适配截图是明确标记的呈现层夹具，不作为实际旅行或 NPC 活动证据。没有修改场景素材。

工作区截图：`../outputs/campus-scene-ink-20260911/`；仓库截图：`production/screenshots/ui-minimal-hud/campus-hud-scene-ink.png`。

Windows 真机视觉、键鼠和性能仍需目标设备验收；本记录不声称跨平台性能提升。
