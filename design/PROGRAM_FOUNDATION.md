# 第一阶段：程序底座

> 状态：已实现并通过回归
>
> 范围：校园运行时的权威状态、命令、事务、事件、随机数、内容注册与检查点
>
> 兼容原则：当前可玩版仍使用旧 `runtime.World` 和 Godot `world_snapshot` v2

## 1. 本阶段解决的问题

后续所有校园系统必须建立在同一组规则之上：玩家、普通 NPC、深度 NPC、LLM 和剧情系统都只能提交命令，不能直接修改金钱、物品、关系、任务或战斗状态。

本阶段新增的程序底座提供：

1. 组合式权威 `WorldState`，避免继续把功能堆进旧 `World` 大类。
2. 带幂等 ID、调用来源和预期世界版本的 `SimulationCommand`。
3. 原子 `WorldKernel` 事务；任何失败都不会留下部分修改。
4. 已发生事实才可写入的 `SimulationEvent`。
5. 按系统命名的确定性随机流，新增战斗随机不会改变 NPC 决策随机序列。
6. 统一内容注册中心、跨文件引用检查和内容版本哈希。
7. 带校验和的检查点、随机数状态和追加式事件日志。
8. 面向未来 Godot 接口的严格命令解析与只读状态视图。

## 2. 权威状态与事务

`WorldState` 当前组合十二个聚合：

- population
- places
- inventories
- relationships
- organizations
- forums
- tasks
- situations
- battles
- knowledge
- narrative
- cognition

系统只能在 `TransactionContext.state` 的事务副本上修改数据。`WorldKernel` 的处理顺序为：

```text
命令解析
→ 幂等 ID 检查
→ expected_world_revision 检查
→ 在世界与 RNG 副本上执行
→ 验证世界不变量和系统不变量
→ 生成确定性事件 ID
→ 追加事件批次
→ 一次性替换已提交状态与 RNG
```

下列任一情况发生时，世界状态和随机数状态都会一起回滚：

- 行动处理器抛出异常；
- 世界或系统不变量失败；
- 事件日志写入失败；
- 处理器返回不提交结果。

一个合法但失败的行动可以标记 `performed=true, success=false`；一个被规则拦截但需要留下公开事实的行动可以标记 `performed=false, commit=true` 并产生阻断事件。这与现有物品检定和仪式阻断语义兼容。

## 3. 幂等与并发冲突

每条命令必须包含：

- `command_id`
- `actor_id`
- `action_id`
- `target_ids`
- `parameters`
- `expected_world_revision`
- 发出时的 day、phase、minute
- `source`: player / rule / llm / narrative

同一 `command_id` 和同一内容重复提交时，直接返回首次结果，不重复执行。成功、失败和未执行命令的回执都会进入检查点，因此读档后仍保持幂等。相同 ID 配不同内容会被拒绝。预期版本与当前世界版本不一致时会触发版本冲突，调用者必须读取新快照并重新生成合法命令。

这为后续任务抢单、交易、使用物品和战斗指令提供统一的并发语义。

## 4. 随机数规则

`DeterministicRngPool` 由一个主种子派生具名随机流，例如：

- `npc_generation`
- `npc_decision`
- `schedules`
- `economy`
- `tasks`
- `checks`
- `combat`
- `narrative`

每个流互相独立。事务仅使用随机流副本，事务失败不会偷走随机结果。检查点保存已经创建的所有随机流状态，读档后从准确位置继续。

后续代码禁止直接使用模块级 `random`，也不能为了方便共用旧 `world.rng`；迁移一个系统时必须为其指定稳定的流名。

## 5. 内容注册中心

`ContentRegistry` 当前统一加载并校验：

- 36 种物品和 36 个物品用途；
- 5 家旧版商店、物品放置和通道；
- 21 个旧版地点映射；
- 8 个学院；
- 12 个社团；
- NPC 生成约束；
- 28 天 Demo 日历；
- 8 种敌人原型。

注册中心会拒绝：

- 重复内容 ID；
- 不支持的内容 schema；
- 逃出 `content/` 的路径；
- 用途、商店、放置、通道引用不存在的物品或地点。

内容版本由各 JSON 的规范化内容生成，不包含 Mac 或 Windows 的绝对路径。未来存档可据此判断内容是否兼容。

## 6. 检查点、事件日志与版本边界

程序底座检查点使用：

```text
checkpoint_format = campus-kernel
kernel_checkpoint_version = 1
```

它包含世界状态、处理过的命令回执、随机流状态、内容版本、内容清单和 SHA-256 校验和。写入使用临时文件替换，读取时会验证格式、版本、校验和、主种子和内容版本。

事件日志每次事务写一行批次，不在启动时清空；重新打开时检查事件 ID 是否连续。

这里的检查点版本与 Godot 公共快照版本不是同一个概念。当前 `world_snapshot.schema.json` 继续保持 v2。只有校园 NPC、校园地点、双论坛等数据真正接入运行时并准备供 Godot 消费后，才发布公共快照 v3。

## 7. 本阶段没有改变的内容

- 没有替换当前 Godot 主场景、地图、角色控制或快捷键。
- 没有把旧廷根 NPC 转换成校园 NPC。
- 没有修改现有交易、物品、仪式或 LLM 接口行为。
- 没有调用外部 LLM。
- 没有删除旧工程、旧素材或 ZIP。
- 没有合并到 `main`。

程序底座目前与旧运行时并存。后续按系统逐个迁移，迁移完成一个系统才让该系统的数据进入 `WorldState`。

## 8. 代码位置

- `simulation/domain/world_state.py`：权威状态与时钟
- `simulation/domain/events.py`：事件草稿和已提交事件
- `simulation/actions/commands.py`：统一命令与结果
- `simulation/systems/transactions.py`：事务内核
- `simulation/systems/randomness.py`：具名确定性随机流
- `simulation/systems/content_registry.py`：内容注册、版本和引用检查
- `simulation/persistence/kernel_checkpoint.py`：检查点读写
- `simulation/persistence/ledger.py`：追加式内核事件日志
- `simulation/api/commands.py`：严格命令解析
- `simulation/api/views.py`：最小只读状态视图
- `contracts/simulation_command.schema.json`：命令契约
- `contracts/command_result.schema.json`：命令结果契约
- `contracts/kernel_checkpoint.schema.json`：检查点契约

## 9. 验收结果

- 当前工程测试：175 项通过。
- 旧版工程测试：46 项通过。
- Python 全量编译：通过。
- JSON Schema 解析：通过。
- `git diff --check`：通过。
- 固定种子 42、规则模式 28 天：完整运行。
- Godot 4.7.2 无界面编辑器导入：通过。
- Godot 4.7.2 主场景启动、本地服务连接和旧地图载入：通过。

## 10. 下一阶段入口

下列“校园地点语义层与校园 NPC 生成”工作现已完成，结果见
[`CAMPUS_MAP_AND_POPULATION.md`](CAMPUS_MAP_AND_POPULATION.md)：

1. 定义校园区域、建筑、室内点位、通行关系和开放时间。
2. 将现有地图灰盒坐标映射到校园地点 ID，但暂不更换最终美术。
3. 按 6000 人统计背景和 200 名持久 NPC 约束生成校园人口。
4. 把生成结果写入 `WorldState.population` 与 `WorldState.places`。
5. 通过统一命令实现最小 `MOVE`，证明玩家和 NPC 使用同一地点与事务规则。
6. 接入 Godot 只读校园快照和最小调试 UI 后，再开始日程与行动次数。

地点粒度已经确定为“室外分区 + 建筑 + 关键固定房间 + 普通房间池”。普通教室和宿舍房间存在语义实例但不逐间制作场景；医院、心理中心、档案室等关键空间保持独立。
