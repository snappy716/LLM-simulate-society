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
当前 `simulation/runtime.py`、旧快照握手和部分 Godot 共用组件仍有校园依赖，
不是已经完成全仓库旧城镇下线；需按 `LEGACY_RETIREMENT.md` 先解耦再删除。

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
tests/                        校园回归、契约与仍在使用的兼容功能测试
design/                       系统与架构设计
production/                   发布和迁移检查
```

依赖方向为 `game -> simulation/api -> simulation`。模拟内部由运行时协调
`domain/actions/systems/cognition/narrative/persistence`，这些模块不能反向依赖
Godot。`content` 与 `contracts` 是数据边界，供两端共同读取。

领域实体、人口生成、关系网络、经济补给、事件日志和快照写入已经由对应
模块实际负责。`simulation/runtime.py` 保留跨系统的回合编排；尚未单独拆出的
复杂流程通过稳定边界转发，后续可逐个迁移，不需要改变 Godot API 或玩法规则。

物品与交易已经使用数据驱动内容和独立领域模型实现：`domain/inventory.py` 负责
物品、背包、商店和回执，`systems/economy.py` 负责报价、不变量与原子结算，
Godot 只能通过本地 API 请求交易，不能直接修改资金或库存。

目标发行平台是 Windows，开发验证可在 macOS 进行。Godot 启动桥在 Windows
调用 `python`，在 macOS/Linux 调用 `python3`；仓库代码不保存平台绝对路径。
