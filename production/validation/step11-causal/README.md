# 同检查点七天对照证据

- `configuration.json`：实际执行源码 SHA-256、基线提交、内容版本、自然前置条件。
- `comparison.json`：两分支同起点校验及终态，不是第 11 步整体通过声明。
- `causal-review.json`：按帧整理私有案例的真实链路与玩家可用视图；`compact_review.py` 可从原始输出重新生成。可用视图不等于玩家实际查看。
- `raw-audit.tar.gz`：原始检查点、前置真实命令和两个七日分支的完整命令/事件/观察。全部为规则生成的游戏测试数据，无个人 API；单独压缩保存，不参与游戏加载。
- `seven-day.log`：两分支各 28 次推进及完成标记。
- `python-full.log`、`python-modules/`：81 模块 / 755 项最终全量通过；`python-target.log` 是 9 项新增专项。
- `godot-full.log`：实际后台 Godot 全部 51 项流程通过，本批不新增 UI。

解压原始审计时请使用新的临时目录；可从仓库根目录执行 `python3 -m production.run_causal_comparison --days 7 --seed 42 --output <新目录>` 复现。结果边界见 `production/STEP_11_CAUSAL_FOUNDATION_ACCEPTANCE.md`；真实 LLM 和夜间玩家分支尚未在本批验收。
