# 交友与恋爱首批证据

- `python-final.log`：修正后完整一轮，92 模块 / 883 项，退出 0；`python-final-modules.tar.gz` 保存逐模块日志。
- `targeted-final.log`：从该最终完整一轮提取的 16 项新专项。
- `godot-final.log`、`godot-final-logs.tar.gz`：61 条实际后台 Godot 流程及各自日志，退出 0。归档仅含日志，不包含临时设置或游戏存档。
- `seven-days.log`、`run_seven_days.py`：两种子各七日，不注入关系或约会；自然长相处和正式关系均为零。不是丰富恋爱体验通过证明。
- `previous-save.log`、`check_previous_save.py`：读取上一版实际 Godot 保存流程的检查点，验证状态/RNG/源文件保持，仅加载修订号按原规则更新。未复制或上传该存档。
- `targeted-initial-*.log`：存档辅助函数签名错误、未来预算夹具错误及修正说明见本批验收文档。
- `python-interrupted-*.log`：修正性格字段、补充结束关系上下文时主动终止的早期全局，不计入最终通过结果；`targeted-ended-context.log` 是期间的专项记录，不替代最终源码回归。

正式关系判断目前为规则首版。全部测试不调用游戏的付费 LLM API；未来真实模型质量与自然交往节奏需要另行评估，不能将人工高关系夹具当作自然涌现。
