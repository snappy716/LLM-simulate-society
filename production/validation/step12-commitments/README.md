# 共享确认约定与本人日程验收档案

2026-09-09。范围与限制见 `../../STEP_12_COMMITMENTS_ACCEPTANCE.md`。

- `targeted.log`：新增约定与原出击、社交、支持联合 39 项通过。
- `python-initial.log` / `python-initial-modules.tar.gz`：首轮全量 795 项，唯一失败为 UI 目录仍期待 15 个入口。
- `theme-rerun.log`：入口计数修正为 16，原有图标/唯一性/目录映射条件保留，10 项通过。
- `python-final.log` / `python-final-modules.tar.gz`：修正后重新完整运行，`GLOBAL_OK 85 795`，退出 0，包含多日因果对照模块。
- `godot-target-initial.log` / 对应 `flow-logs`：日程日期小数显示断言失败；实际 UI 修正整数显示。
- `godot-target-second.log` / 对应 `flow-logs`：实际日程预约/取消、支持预约页成功，旧首页计数失败；不是三项全绿。
- `godot-initial.log` / `godot-initial-flow-logs.tar.gz`：首轮全局遇到同一旧首页计数失败。`layout-rerun.log` 为 16 入口、三尺寸专项通过。
- `godot-final.log` / `godot-final-flow-logs.tar.gz`：修正后重新完整执行 53 项，`GODOT_CHECKS_OK 53 flows`，退出 0，无脚本错误。压缩包只含 106 份 fixture/Godot 日志，不含个人设置、存档或图片。

复跑 Python：在仓库根目录执行 `python3 production/validation/step10-followup/campus_field_global_check.py /tmp/campus-calendar-check`。Godot：`python3 production/run_godot_checks.py --godot <本机Godot路径>`。原始日志压缩包可解包到单独临时目录核对，不需要付费 API。

测试中的同意、位置或冲突边界注入明确属于夹具；实际命令、原子拒绝、存读档和 UI 走正式运行时，不冒充自然 LLM 行为。未测试 Windows 原生发行，未实施主线或合并 main。
