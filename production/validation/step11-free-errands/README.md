# 第 11 步自主附加采购验收证据

日期：2026-09-09。说明见 `../../STEP_11_FREE_ERRANDS_ACCEPTANCE.md`。

- `python-final.log` / `python-modules/`：最终全量 `GLOBAL_OK 84 787`，进程退出 0。
- `python-initial.log` / `initial-python-modules/`：首轮全部执行，两处旧行为假设失败，保留原文；`effects-rerun.log` 与 `cognition-rerun.log` 记录修正测试后的专项，之后再次执行上述最终全量。
- `targeted.log`：29 项组合计划、规则、存档/重放与审计专项通过。
- `godot.log` / `godot-flows/`：52 项后台 Godot 流程首轮全部通过，退出 0；`free_errands` 的计划、初始条件、日志告知及展示同地是明确的夹具设置，不冒称自然模型行为。
- `configuration.json`：同检查点、七日、兼容模型选项和 213 项冻结执行文件的 SHA-256。主审计正常结束，终端返回 `LIVE_CAUSAL_COMPARISON_OK`、退出 0，结束时全部源码哈希一致。
- `comparison.json`：相同世界与 RNG 的规则无人、LLM 无人、LLM 玩家参与两条对照轴。
- `*/requests.json`：实际请求、返回、HTTP 状态、响应标识、UTC 时间与服务商用量，不含认证头或 Key；`usage-ledger.json` 为本轮合计，不是账户总账。
- `*/coverage.json`：只计算实际观察到的模型日程时段，排除最后一天尚未执行的后续时段。
- `errand-receipts.json`：实际采购、授权选择、后续主体结果的独立复算；`audit_errand_receipts.py` 是只读复算脚本，不调用 API。三分支齐全、无越权/覆盖/缺失后续断言通过，进程退出 0。
- `raw-worlds.tar.gz`：原始初始检查点及三分支完整 JSON（命令、事件、每时段快照、请求和世界结果）。解包后以其目录作为参数运行 `python3 audit_errand_receipts.py <解包目录>`，可重复得到收据结果；不需重新进行付费测试。

所有自动认知调用均属于正式跨日命令；两付费分支 280 次每日规划、39 次措辞、1 次其他选择，另 1 次连接探测。共 321 次、1,316,043 Token；所有 NPC 请求带共用规则，全部 HTTP 成功，无用量缺失、协议拒绝、回退或预算阻断。模型选择、实际完成与长期玩法质量是不同证据，不把某个时段存在完成记录误写成原计划全部完成。

未纳入私人文档、个人 Key 或主线制作；不等于 Windows 原生发行测试。
