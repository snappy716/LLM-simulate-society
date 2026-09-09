# 第 11 步第二批验收证据

日期：2026-09-09。基线提交：`02fbc9f58e07424a4b83f3da4fdc30b798ebe02e`。

- `python-full.log` 与 `python-modules/`：81 模块、760 测试，含最终 14 项因果专项；退出 0。
- `godot-full.log`：实际 Godot 4.7.2 后台 headless，51 流程、退出 0；不是截图或 Windows 原生发行验收。
- `seven-day.log`：最终 v3 双分支各七日，`CAUSAL_COMPARISON_OK`、退出 0。
- `configuration.json`：实际复用的自然检查点、策略和 209 项源文件哈希，执行后与当前运行文件逐项一致。基线 git 提交不包含这批尚待提交的更改，精确版本以该源码清单为准。
- `comparison.json`：同一事件两条实际履历、执行者、关系变化及调用量，API 为 0。
- `causal-review.json`：压缩摘要；“玩家可用投影”不等于玩家已经读取，`non_advance_results` 才记录正式介入命令。
- `raw-audit.tar.gz`：原始 initial-checkpoint、bootstrap-commands、unattended、participant JSON，保留完整命令/世界事件/审计快照。复用检查点时 bootstrap 为空，原始自然生成过程在第一批 `step11-causal/` 归档。

重新运行（从压缩包解出检查点到独立目录后）：

```sh
python3 -u -m production.run_causal_comparison --days 7 --player-policy participant --checkpoint /path/to/initial-checkpoint.json --output /path/to/new-audit
python3 production/validation/step11-participant/compact_review.py /path/to/new-audit /path/to/review.json
```

本批玩家实际参与 7 场卡牌战斗并正常休息，改变同一异常首次夜间执行者/时间，但未获得本人异常陈述；白天策略自然触达、实际 LLM 增益与故事可理解性仍待验证。旧 probe/v1/v2 试跑均不算本批最终七日证据。详情见 `production/STEP_11_PARTICIPANT_ACCEPTANCE.md`。
