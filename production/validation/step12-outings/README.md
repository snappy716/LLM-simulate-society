# 自愿相处与约会：验证归档

2026-09-10，离线测试，不调用付费 API。

第一轮全局运行在审查发现最小世界视图缺失固定校园地点时，被主动停止（Python/Godot 进程退出码 143）。原有 `test_kernel_api_contracts` 独立复现 `mirror_lake_square` 缺失错误；不是超时重启，也没有把被中止的流程统计为完整通过。

修复仅令日程选项跳过当前世界不存在的地点，不改原有契约测试。最终同源码完整重跑：89 模块/844 项 Python、57 条 Godot 流程全部通过，两进程退出码均为 0。

- `python-final.log` / `python-final-modules.tar.gz`：全局汇总及 89 份逐模块日志。
- `godot-final.log` / `godot-final-flows.tar.gz`：全局汇总及 114 份逐流程日志（仅日志，无个人设置/存档）。
- `minimal-view-failure.log` / `minimal-view-fixed.log`：实际故障与修复后复测。
- `python-initial-interrupted.log` / `godot-initial-interrupted.log`：首轮中止时的进度，不是完整通过。
- `check_previous_save.py` / `previous-godot-save.log`：真实上一批 Godot 存档在新运行时加载，除正常读档 revision 外世界与 RNG 不变，源文件不变，无补造相处记录。
