# 比赛、节庆与第 12 步验收证据

仅测试日志与显式验收脚本；不包含用户存档、API 设置或密钥。后台 macOS Godot 不等于 Windows 实机发行验收。本目录的 API 调用为 0。

## 最终证据

- `godot-final.log`、`godot-final-logs.tar.gz`：完整 65 条后台 Godot 场景/HTTP/显式投影流程，进程退出 0。包括赛事与节庆的手机报名、正式参与、结果、重复拒绝，原有生活/社交/战斗等仍运行；不把显式投影夹具当作自然 NPC 行为。
- `contracts-final.log`：28 项最终活动/API/人物日志专项；`targeted-final.log`：此前活动与课程兼职 23 项，不能取代全量。
- `natural-42.log`、`natural-314.log`：各十四日最终世界规则无人推进；真实学院技能、资源、报名与结果，无玩家代办和计划/成绩注入。运行脚本 `run_natural.py`。
- `previous-godot-save.json`：`check_previous_save.py` 对实际上一版 Godot 检查点的只读核验；仅新定义/启用时点/内容身份改变，旧账本、RNG 和源文件不变。检查点本体不上传。
- `integrated-42.log`、`integrated-314.log`：`audit_integrated_life.py` 两组完整十四日通过，含第七日全部世界字段/RNG 落盘读回及真实续跑；课程、工资、社团晋升、医疗、相处与前序战斗/任务均来自实际执行，API 0。
- `historical-step11-receipts.json`：使用既有 `step11-free-errands/audit_errand_receipts.py` 对其原始 `raw-worlds.tar.gz` 三分支的只读复算，退出 0、违规项均空。这是历史真实 API 样本复算，不是本次重新付费测试。
- `runtime-content-sha256.txt`：最终运行时代码、内容、契约和 Godot 脚本/流程 SHA-256 清单，用于核对验收期间未改执行源。
- `python-final.log`、`python-final-modules.tar.gz`：最终干净全量 `GLOBAL_OK 95 906`；95 模块、906 项，全部模块返回 0，不是失败初轮与补测拼接。
- `source-check.log`：368 项最终执行源/内容哈希核对一致。之后仅整理文档与测试证据，不修改运行时。

## 初轮与未完成轮次

- `unit-initial.log`、`unit-before-migration-refresh.log`：显式夹具字段/时钟/序列化差异及冻结清单顺序问题，均保留原文。
- `natural-before-motivation-42.log`、`choices-before-motivation.json`：首轮节庆自然不可达及只读候选诊断；不是最终行为样本。
- `privacy-initial.log`、`contracts-initial.log`：投影隐私复查首轮，列表类型的通用战斗效果不能当作字典；修正后专项和完整 Godot 再验。
- `python-interrupted-*.log`、`godot-interrupted-*.log`：因补入真实学院技能及隐私修复而主动中断的旧代码轮次，不统计通过数量。
- `python-migration-chain-failed.log`、`python-migration-chain-failed-modules.tar.gz`：完整 Python 首轮，仅最新迁移终点旧断言失败；`migration-chain-initial.log` 为该模块原文，`migration-chain-rerun.log` 是增加新迁移边精确断言后 4 项复测，不替代干净全量。
- `godot-new-flows.log`：首轮两条新增流程，仅作追溯，最终以完整 65 条为准。
- `integrated-42-initial.log`、`integrated-314-initial.log`：世界实际推进十四日后，汇总误以为普通讲座也有专用结果/工资收据而报错；仅修正审计器，完整重跑两组，不把该轮当作综合通过。

## 综合核对脚本

`audit_integrated_life.py` 从完整新校园推进十四日，仅玩家 `ADVANCE_PHASE`，逐时段检查权威不变量；第七日将全部世界字段及 RNG 写入临时测试存档、读回精确比较并真实续跑。观察课程、兼职、社团晋升、相处、医疗和比赛结果；不通过强制晋升/恋爱/受伤来凑覆盖。自然未出现的分支由明确夹具测试分别证明，不能混为自然出现。

所有生成的世界对象和存档仅属测试；公开成绩只来自实际参加人，不把背景人口当作出勤。具体规则与验收口径见 `../../STEP_12_EVENTS_ACCEPTANCE.md`、`../../../design/CAMPUS_EVENTS_RUNTIME.md`。
