# UI01 / UI02 验证摘要

2026-09-11。macOS，Godot 4.7.2，测试运行器 Python 3.12.14。未调用付费模型。

## Python

命令：`python3 production/validation/step10-routes/run_python_full.py /tmp/campus-ui01-ui02-20260911`

结果：`GLOBAL_OK 95 910`，退出码 0。逐模块日志在 `/tmp/campus-ui01-ui02-20260911-modules/`。

追加：`python3 -m unittest tests.test_campus_saves tests.test_architecture_contracts`，27 项通过。新增覆盖新世界确认、过期 revision/额外选项拒绝、构建失败不替换、存档和认知运行时保留、兼容列表不改变世界。

## Godot

`production/run_godot_checks.py` 中 STANDARD + FIXTURES 共 67 个流程，按列表偶数/奇数索引分组，不重叠、不省略流程，独立配置、端口和存档。

- 34 项：`campus-godot-checks-182iooy8`，`GODOT_CHECKS_OK 34 flows`，退出码 0。
- 33 项最终重跑：`campus-godot-checks-84mmp90x`，`GODOT_CHECKS_OK 33 flows`，退出码 0。
- 首次 33 项分组 `campus-godot-checks-z3qn7r6g` 在过夜输入测试失败。根因是 SystemMenu 的 `_input` 优先于过场处理 Esc，已增加显式过场优先级；不是放宽断言或延长超时。
- 单独过夜修复复验：`campus-godot-checks-55nbrn1i`，1 项通过。
- 最终追加菜单/启动/存档/主题/手机布局：`campus-godot-checks-txootisy`，5 项通过。

上述目录位于系统临时目录 `/var/folders/b8/q5t81wyd095ff0jlv8c2pjhw0000gn/T/`，每个流程各有日志。临时日志不是发布依赖。

专项标记：`CAMPUS_SYSTEM_MENU_OK title new_confirm cancel new_world guide pause settings save compatible_continue return_title quit_cancel three_sizes components no_paid_api`。

## 实机呈现

后台隐藏启动：`open -g -j -n`，独立离线设置和临时存档；截图脚本 `game/tools/capture_campus_system_menu.gd`。

标记：`CAMPUS_SYSTEM_MENU_CAPTURE_OK actual_new_world offline title pause saves settings component_examples`。渲染日志：`/tmp/campus-ui02-capture.xhCXhJ/godot-delivery.log`，无脚本或渲染错误。静止后台窗口使用 `RenderingServer.force_draw()` 请求真实帧，不伪造截图。

检查标题、新游戏、确认、首次引导、暂停、真实存档、设置和组件样例。窗口适配专项覆盖 960×540、1280×720、1920×1080；长页面采用滚动、固定返回入口。菜单下层 HUD 隐藏并能恢复。

本次完成公共组件和系统入口，不代表所有业务页面已经重排；Windows 真机视觉、键鼠及发行仍需后续验证。
