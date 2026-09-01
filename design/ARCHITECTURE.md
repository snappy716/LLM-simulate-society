# 项目架构

本次迁移采用并行目录，不删除或覆盖 `project-a-0.2/` 与
`emergent_town_demo/`。新目录是后续开发入口，旧目录用于行为对照和回退。

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
tests/                        新架构回归、契约与新旧等价性测试
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
