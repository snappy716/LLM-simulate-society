# 第 10 步第八批验收证据

此目录只接收代码最终冻结后的第二轮全量结果；第一轮 `*-global-final` 在混合终点修复前启动，不作为最终验收。

- `seed42-seven-days.json`、`seed7-seven-days.json`：各 28 次正式时段推进，无玩家帮助、无 API；不是付费模型故事质量证明。
- `resident-cap-probe.log`：同区域 95 人、原上限 18、同地点目标按旧 ID 排第 34 的只读复核。修正显示优先级而非修改人口位置。
- `mixed-closure-before-fix.log`：真实支持先清心结、真实夜战再清外壳，旧实现固定 `easing` 导致全局状态拒绝的失败证据；不是本版测试失败。
- `python-full.log` 与 `python-modules/`：最终 80 模块 / 746 项全部通过；`run_python_full.py` 从仓库根目录运行，参数为临时日志前缀，用四进程执行完整发现列表并核对数量。
- `godot-full.log`：最终 51 项全部通过；`godot-routes/`、`godot-anomaly/`、`godot-afterimage/` 保留本批直接相关实际流程。结果以 `production/STEP_10_ROUTES_ACCEPTANCE.md` 为准。

Godot 采用实际引擎后台 headless 测试；不等于最终画面审核或 Windows 原生发行验收。新 Godot routes 流程使用真实 HTTP 服务、场景人物、面板按钮与三种窗口尺寸；夹具预置关系/知识/物资，支持与战斗结果由实际行动产生。
