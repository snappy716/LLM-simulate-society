# 过夜并行验证证据

2026-09-10。没有付费 API 调用，没有打包接口设置、密钥或游戏存档。测试日志为本地生成；验收说明见 `production/OVERNIGHT_PARALLEL_ACCEPTANCE.md`。

- `latency-025s.log` / `latency-3s.log`：固定接口等待时间、相同世界的完整过夜墙钟对照，不是实际服务商/朋友电脑测量。
- `godot-final.log` / `godot-final-flows.tar.gz`：后台 Godot 全部流程汇总和逐流程日志，`parallel/fixture.log` 含实际回环 HTTP 的并发/账本核验；归档仅包含 `.log`。
- `python-final.log` / `python-final-modules.tar.gz`：完整 Python 回归汇总和逐模块日志。
- `previous-save.log`：复用 `production/validation/step12-outings/check_previous_save.py` 验证真实旧 Godot 存档原文件、世界与 RNG 未改变（除既有读档 revision 保护），内容版本 `74314dd2ea32e235`。
- `related-tests.log`：初始 14 项相关测试。
- `initial-fixture-error.log` / `cache-fixture-fixed.log`：缓存测试夹具原本遗漏必填字段，补齐后单项通过；完整结果以 `python-final.log` 为准。
- `initial-ui-test-order-error.log`：原测试在重载配置后才检查前一次应用的提示文本；调整断言顺序后，完整 Godot 回归通过。未放宽原有断言。
- `python-pre-audit-guard.log` / `godot-pre-audit-guard.log` / `godot-pre-audit-guard-flows.tar.gz`：首轮通过记录；随后复查发现派生审计适配器不适合自动并行，增加兼容屏障并重跑全局，最终结果以 `*-final*` 为准。`audit-guard-fixed.log` 为新增兼容检查及旧审计测试。
- `python-pre-cache-order-interrupted.log` / `godot-pre-cache-order.log`：第二轮记录。补充缓存审计顺序后，旧 Python 进程组主动停止（143），Godot 已完成（0），不作为最终源码通过证据。`cache-order-fixed.log` 是新增混合在途/缓存与原缓存检查。

复现完整验收：

```sh
python3 production/validation/step10-routes/run_python_full.py /tmp/campus-parallel-recheck
python3 production/run_godot_checks.py --godot /path/to/Godot
python3 production/measure_overnight_latency.py --delays 3 --concurrency 1 10 20
```

Godot 流程自动使用后台/headless、隔离设置/存档目录和回环端口；模拟提供方限制在本地，不读取私人 API 设置。
