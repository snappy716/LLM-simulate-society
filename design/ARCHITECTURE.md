# 项目架构

> 校园 Demo 的目标架构、模块职责、API、存档与四个月迁移顺序见
> [`CAMPUS_DEMO_ARCHITECTURE.md`](CAMPUS_DEMO_ARCHITECTURE.md)。本文件继续记录
> 已完成的第一轮目录迁移和现有可运行边界。
>
> 第一阶段程序底座的实现范围、版本边界与验收结果见
> [`PROGRAM_FOUNDATION.md`](PROGRAM_FOUNDATION.md)。
>
> 校园地点粒度、200 名常驻人口和 Godot 道路/入口约定见
> [`CAMPUS_MAP_AND_POPULATION.md`](CAMPUS_MAP_AND_POPULATION.md)。

2026-09-05 用户已允许删除旧城镇，原先“保留旧目录”的约束撤销。
独立的 `project-a-0.2/`、`emergent_town_demo/` 和原 ZIP 已退出仓库，历史版本可从 Git 恢复。
当前正式入口只启动校园；旧 runtime、旧桥接、旧客户端与纯城镇内容已物理移除，
不再以旧快照握手或初始化旧世界。校园复用模型与素材保留，恢复基线和验收见
`LEGACY_RETIREMENT.md`。历史设计文档和私人运行数据不属于本次删除范围。

```text
game/                         Godot 项目
simulation/
  domain/                     NPC、物品、组织、计划等领域模型
  actions/                    统一行动注册、校验与执行
  systems/                    时间、人口、关系、情报、经济与组织边界
  cognition/                  观察、记忆、反思、规划与对话边界
  narrative/                  故事线、局势、主线锚点与后果链
  persistence/                存档、事件日志与版本迁移
  api/                        Godot 本地 HTTP 桥接
content/                      仅存放数据内容，不放运行逻辑
contracts/                    跨进程请求、事件与快照 JSON Schema
tests/                        校园回归、契约与已知校园档迁移测试
design/                       系统与架构设计
production/                   发布和迁移检查
```

上述目录职责包含目标边界，不代表每项功能均已完成。认知当前包括提供器和焦点槽，
校园记忆与计划等逻辑仍有实现位于 `systems/campus_*`；完整长线计划与叙事待路线后续步骤贯通。

依赖方向为 `game -> simulation/api -> simulation`。模拟内部由校园内核协调
`domain/actions/systems/cognition/narrative/persistence`，这些模块不能反向依赖
Godot。`content` 与 `contracts` 是数据边界，供两端共同读取。

领域实体、人口生成、关系网络、经济补给、事件日志和快照写入已经由对应
模块实际负责。校园由 `CampusKernelBridge` 注册统一事务处理器并协调时段，
`WorldKernel` 负责事务，`WorldState` 是状态权威。旧 `simulation/runtime.py` 已删除。

物品与交易已经使用数据驱动内容和独立领域模型实现：`domain/inventory.py` 负责
物品、背包、商店和回执；`systems/campus_inventory.py`、`campus_trade.py` 和
`campus_supply.py` 负责校园库存、私人报价/结算与供货，
Godot 只能通过本地 API 请求交易，不能直接修改资金或库存。

目标发行平台是 Windows，开发验证可在 macOS 进行。Godot 启动桥在 Windows
调用 `python`，在 macOS/Linux 调用 `python3`；仓库代码不保存平台绝对路径。
