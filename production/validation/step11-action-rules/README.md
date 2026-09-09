# 共用行动规则第一部分验收证据

基于已上传 `62a7e4e`，本批执行代码由 `configuration.json` 的 212 项 SHA-256 固定。不是主体安排/附加行动执行修复已完成的证明。

- `targeted.log`：最终 14 项专项，退出 0。
- `python-full.log`、`python-modules/`：83 模块、774 项全量通过，退出 0。
- `godot.log`、`godot-flows/`：实际 macOS 后台 headless 全套 51 项首轮通过，退出 0；未验收 Windows 原生发行。
- `live-run.log`：真实三分支两日 `LIVE_CAUSAL_COMPARISON_OK`，退出 0。运行 `python3 -u -m production.live_causal_audit --checkpoint <上批已有检查点> --output <新目录> --days 2`，没有注入结果或为测试强迫人物同意。
- `comparison.json`、各分支 `coverage.json`：同一第 3 天上午至第 5 天上午的正式推进和结果；完整代码哈希一致。
- `llm-*/requests.json`：80 次日程规划、11 次互动措辞均携带共用规则版本 1，HTTP 成功，无协议拒绝或回退；其中的请求内容、日程选择和规则上下文可逐条复核。没有 API Key 或认证头。
- `usage-ledger.json` 和 `probe/requests.json`：另含一次探测，共 92 次请求、326,822 Token，无缺失用量。这是本轮账本，不是账户总账；请求/汇总/归档副本不能重复相加。
- `raw-worlds.tar.gz`：初始世界/RNG 和三个分支原始命令、事件、帧。未来时段不当成已执行，观察视图不当成玩家实际阅读。

边界及下一部分见 `../../STEP_11_ACTION_RULES_ACCEPTANCE.md`。不能用这两日的匹配率与上批七日样本直接比较并宣称模型能力提升；免费采购仍可能顶掉主体安排，后续须实现人物自主组合计划的实际执行链。
