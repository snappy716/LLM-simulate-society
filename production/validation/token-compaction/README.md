# Token 输入精简的离线验收

说明见 `production/LLM_TOKEN_OPTIMIZATION.md`。结果：针对性测试 19 项通过；全量 Python 86 模块、804 项通过；Godot 53 流程通过；两个全量进程退出码均为 0。

- `prompt-size.json`：基于此前 320 条历史请求重建的新旧输入字符量；不是账单或 Token 节省实测。
- `targeted.log`：发送格式、完整性、共用规则与双接口针对性测试。
- `python-global.log` / `python-module-logs.tar.gz`：全量 Python 汇总及逐模块日志。
- `godot-checks.log` / `godot-flow-logs.tar.gz`：后台无头 Godot 汇总及逐流程日志。

本轮不调用真实模型，不复制个人 API 设置、存档或截图。复现全量验证：

```sh
python3 production/validation/step10-followup/campus_field_global_check.py /tmp/campus-token-compaction-repeat
python3 production/run_godot_checks.py --godot /path/to/Godot
```
