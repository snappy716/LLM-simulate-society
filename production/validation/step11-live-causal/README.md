# 第 11 步真实 LLM 同检查点七日对照证据

2026-09-09，开发分支基线 `d10e288` 加本批审计代码；运行源码以 `configuration.json` 中 211 项 SHA-256 为准。各分支从相同第 3 天上午检查点/RNG 开始，至第 10 天上午。没有注入世界结果、人物身份或必胜战斗。

## 文件与结果

- `python-full.log` / `python-modules/`：最终 82 模块、767 项通过，退出 0。`targeted.log` 为之前的 23 项专项；之后的离线调用校验细化由最终全量覆盖，以全量为准。
- `godot-initial.log` / `godot-initial/`：实际后台 Godot 首轮 43 项通过，afterimage 测试数据准备 60 秒超时，该项尚未进入 Godot 场景。原始失败保留。
- `godot-remainder.log` / `godot-remainder/`：不修改游戏或断言，重跑 afterimage 及后续 7 项，8 项通过、退出 0。两轮合计覆盖原全套 51 项，不伪称首轮全绿。测试为 macOS headless，不等于 Windows 原生发布验收。
- `live-run.log`：`LIVE_CAUSAL_COMPARISON_OK`，退出 0；源码哈希一致。启动命令为 `python3 -u -m production.live_causal_audit --checkpoint <已有检查点> --output <新目录> --days 7`，Key 仅终端无回显输入。
- `comparison.json`：保持玩家策略不变的规则/模型对照，以及保持模型模式不变的无人/玩家对照。只对同一个被审计案例汇总，其他案例的玩家支持不混入其中。
- `llm-*/requests.json`：真实服务商响应 ID、时间、模型、HTTP、返回用量及受限请求/响应；没有认证头或 Key。`coverage.json` 记录观察到的模型计划和时段末活动，不把未来时段算成已执行。
- `usage-ledger.json`：本轮独立账本，共 326 次请求、809,943 Token，无缺失用量，含 `probe/requests.json` 的 1 次探测。各请求、汇总、压缩归档是同一批数据的不同表示，不能相加重复计费；也不代表账户所有历史使用。
- `raw-worlds.tar.gz`：完整初始检查点、规则无人/LLM 无人/LLM 玩家参与的原始命令、事件、帧和模型请求。审计内部世界与玩家可获得投影分开；后者可获得不等于玩家实际阅读，需看正式命令。

## 解释边界

本轮测量通过不等于第 11 步或游戏自由度目标已经完成。具体结果、免费采购顶掉主体安排的实际缺口、社交失败分类，以及用户确认的共用规则/自主选择后续见 `../../STEP_11_LIVE_CAUSAL_ACCEPTANCE.md` 和 `../../../design/LLM_ACTION_RULES.md`。不通过增加预算上限、强迫同意或修改测试世界来宣称改善。
