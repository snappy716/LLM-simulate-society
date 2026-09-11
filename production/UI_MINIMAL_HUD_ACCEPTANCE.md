# 极简校园 HUD · U1a 验收

日期：2026-09-11。开发基线：`4e943ef`，分支 `codex/campus-demo-architecture`。不合并 main。

## 本批范围

- 用户确认的六枚功能图标重新绘制为项目内透明 SVG，冰白/明蓝；无按钮底框，手机空屏，仅卡牌与关系保留月相。
- 左上地点、第 N 天、星期、时段；下方真实追踪事项/已确认约定，默认展开一件，可切换、折叠、打开原详情。没有事项就不编造展示，选择与折叠偏好跨场景保留。
- 手机左下；地图、队友、人物与物品、卡牌库、关系在右上。
- 人物状态/随身物品共用入口与页签；背包默认自有物品；卡牌库复用角色八张牌组配置，展示费用/效果/基础效力/作用范围；关系复用交友、恋爱和自愿相处约会。
- 手机顶部“时间与镜头”保留结束时段、进出里世界与镜头倍率。原调试文字/状态面板/镜头按钮不再常驻；素材授权提醒移入校园相册。
- 室内大厅和室外共用 HUD。消息使用权威消息 ID 比较新到达记录，按日期+时段最多一次短震动；同次客户端会话中跨场景/重开手机不重置。初次同步、读档历史、遗留未读、自己的消息不触发。
- 业务操作继续走 SimulationBridge 与已有权威校验，不改变 NPC 决策、主要行动计费、卡牌结算或多伴侣规则。不调用付费 LLM。

## 验证状态

验收通过：95 个 Python 模块 / 906 项测试，66 条后台 Godot 流程完整通过；最终 HUD 专项与实际渲染也通过。逐项进程成功标记见 [测试摘要](validation/ui-minimal-hud/summary.md)。上传状态以远端分支核验为准，不把本地测试当作已发布。

首次全量 Godot 在 afterimage 复杂夹具准备阶段超过 60 秒；该次未记为通过。改用已配置的 Python 3.12.14 运行测试器后，原等待上限、断言和夹具不变，单项与重新开始的完整 66 条均通过。

- `test_campus_minimal_hud.gd`：960×540 / 1280×720 / 1920×1080，六枚图标范围、无底框、直接入口、人物物品页签、卡牌、关系、时间/镜头、手机通知基线与时段去重、重建 HUD、长事项折叠/切换、室内地图入口、浏览不扣行动。
- `test_campus_save_flow.gd`：实际保存、覆盖、备份、购买后读档、场景重建，并验证手机消息基线替换和重建后不震动。
- 原有 `phone_layout`、`inventory_flow`、`growth` 专项回归覆盖原首页、物品权威操作、知识学习与八张牌组/失败草稿。
- `capture_campus_minimal_hud.gd` 通过后台隐藏启动（`open -g -j`）在 Godot 4.7.2 / macOS / OpenGL Compatibility 实际渲染。已人工查看校园 HUD、人物、物品、卡牌、关系、时间页截图；不是合成概念图。

## 重现

```sh
python3 production/run_godot_checks.py --godot /path/to/Godot
python3 production/validation/step10-routes/run_python_full.py /tmp/campus-hud-python
```

截图脚本：`game/tools/capture_campus_minimal_hud.gd`，最后的用户参数为输出目录。使用独立 `GODOT_SIM_SETTINGS_PATH` / `GODOT_SIM_SAVE_DIR` / `GODOT_SIM_PORT`，不要复用含真实 API 的开发配置。视觉捕获不能使用 dummy 渲染器冒充实机截图。

本机完整截图：工作区上一级 `outputs/campus-minimal-hud-20260911/`。仓库保留 [常驻 HUD 实机截图](screenshots/ui-minimal-hud/campus-hud.png)。截图使用已有联调场景，不构成正式美术授权验收。

## 边界

本批仅常驻信息层与入口接线，内部功能页仍沿用现有表单风格，不代表 U1～U7 全部完成或战斗专用界面已重做。场景图片、人物素材及 NPC 行动规则未改。正式开学公历日期尚未指定，沿用后端第 N 天及周循环。

通知偏好属于客户端会话呈现状态，不加入世界存档；重新启动客户端或载入世界以当前历史作为新基线。Windows 字体、缩放及发行环境仍需 Windows 真机验收，Mac 后台通过不能替代。
