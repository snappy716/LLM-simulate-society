# Project A

> 后续开发入口：[当前实施路线与进度审计](design/IMPLEMENTATION_ROADMAP.md)。先补齐新旧状态与功能 UI，再继续卡牌战斗；场景基于新版七张校园地图。下方早期原型介绍不代表当前功能完成度。

Project A 是一个正在开发中的 2D 等距视角城镇 RPG 原型，目标是把可探索的 Godot 游戏世界与持续运行的 LLM/规则驱动社会模拟结合起来。

当前版本重点验证以下流程：在等距城市地图中控制玩家、生成并显示 200 名具有稳定外观的 NPC、按时间段推进世界、查看 NPC 的状态与计划，以及将模拟人物放置到带有语义标签的城市区域中。

> 当前仍为开发原型，并非完整游戏。校园双论坛、手机对话、社团与组队已有运行时；校园库存、钱包与文字商店已接通。卡牌战斗尚缺敌方回合，持续伤势/治疗、校园 NPC 自主交易、完整调查成长与主线仍需贯通。

## 校园 Demo 目标架构

项目下一阶段将原型迁移为 28 天的大型校园社会模拟 RPG。玩家白天进行校园生活、关系、调查与成长，夜间可以进入受污染月光影响的“夜相”；约 200 名持久化 NPC 即使没有玩家和 LLM 也能交易、接取任务、组织行动并改变世界，约 20 个深度认知槽位用于当前重要人物，其中玩家最多永久觉醒 6 名自己选择的随机 NPC。

- [Demo 世界、玩法与主线大纲](design/CAMPUS_WORLD_AND_GAMEPLAY_DESIGN.md)
- [Godot/Python 目标技术架构与迁移顺序](design/CAMPUS_DEMO_ARCHITECTURE.md)
- [第一阶段程序底座与验收结果](design/PROGRAM_FOUNDATION.md)
- [校园地点、人口与 Godot 导航灰盒](design/CAMPUS_MAP_AND_POPULATION.md)
- [表世界论坛与玩家/NPC 任务竞争](design/CAMPUS_FORUM_TASKS.md)
- [任务关系、社团声望与后续任务链](design/CAMPUS_SOCIAL_CONSEQUENCES.md)
- [十二核心社团运行系统](design/CAMPUS_CLUB_RUNTIME.md)
- [关系邀请与行动小队运行系统](design/CAMPUS_PARTY_RUNTIME.md)
- [当前程序实现 To Do](design/IMPLEMENTATION_TODO.md)
- [NPC 日程与人物日志设计](design/NPC_ACTIVITY_LOG_SYSTEM.md)
- [人物牌与三排卡牌战斗框架](design/CARD_COMBAT_FRAMEWORK.md)
- [人物牌与三排部署运行时](design/CAMPUS_COMBAT_DEPLOYMENT_RUNTIME.md)
- [卡牌战斗回合底座](design/CAMPUS_COMBAT_ROUND_RUNTIME.md)
- [卡牌出牌与效果运行时](design/CAMPUS_COMBAT_ACTION_RUNTIME.md)

本分支先建立可测试的校园领域边界、数据内容和契约，现有 Godot 地图、人物动画、物品交易与旧模拟仍可运行。后续按系统逐项接入，不进行一次性破坏性重写。

## 当前功能

- 64×32 等距 Tile 城市地图与临时 Terrain。
- 玩家移动、碰撞和镜头跟随。
- 分层人物换装：皮肤、头发、衣服、裤装、鞋和武器。
- `idle` 与 `run` 分层动画。
- 基于 `npc_id + world_seed` 的确定性 NPC 外观。
- 200 名 NPC 的职业、关系、记忆、愿望、计划和场景位置。
- Morning、Afternoon、Evening、Late Night 四时段世界推进。
- Q 键人物名册、人物详情、idle 第一帧预览与快速定位。
- M 键世界地图、玩家位置显示、缩放和平移。
- Godot 内置地图矫正模式，可同步修改正交蓝图和游戏 Tile。
- Esc 键 LLM 接口配置面板。
- 离线规则、DeepSeek、DeepSeek 兼容服务和本地 Ollama。
- 21 个公共场景与私人住宅区域的地图语义映射。
- 36 种故事用途物品、5 家文字商店、玩家/NPC 背包与统一买卖结算。

## 项目结构

```text
ProjectA-GitHub/
├── game/                     # 当前 Godot 4 项目入口
├── simulation/               # 领域、行动、系统、认知、叙事、存档与 API
├── content/                  # 地点、NPC、组织、物品、行动与故事数据
├── contracts/                # Godot/Python JSON Schema
├── tests/                    # 新架构回归和新旧等价性测试
├── design/                   # 架构设计
├── production/               # 发布验证清单
├── emergent_town_demo/       # 保留的原 Python 实现，用于对照与回退
└── project-a-0.2/            # 保留的原 Godot 工程，用于对照与回退
```

新开发入口为 `game/` 与 `simulation/`。原版目录暂不删除；重构期间持续用自动化测试验证二者行为一致。详细依赖规则见 [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md)。

## 环境要求

- Godot 4.7 或兼容的 Godot 4.x 版本。
- Python 3.10 或更高版本。
- Windows、Linux 或 macOS；Python 命令需要能从系统 PATH 中调用。
- 可选：Ollama，或可用的 DeepSeek/兼容接口。

离线规则模式不需要 API Key，也不会访问外部 LLM。

## 快速开始

1. 克隆或下载仓库。
2. 确认 `game` 与 `simulation` 保持在仓库根目录。
3. 确认终端能够执行：

   ```text
   python --version
   ```

4. 使用 Godot 打开：

   ```text
   game/project.godot
   ```

5. 运行项目。主场景已配置为：

   ```text
   res://scenes/debug/integration_test.tscn
   ```

Godot 第一次打开时会导入 PNG 人物图集和地图资源，首次加载会比后续运行稍慢。

## 游戏操作

| 操作 | 按键 |
|---|---|
| 移动 | `WASD` 或方向键 |
| 随机更换玩家外观 | `R` |
| 打开/关闭世界地图 | `M` |
| 打开/关闭 NPC 名册 | `Q` |
| 查看附近 NPC | 靠近后按 `E` |
| 打开/关闭物品与交易面板 | `I` |
| 打开/关闭接口面板 | `Esc` |
| 进入/退出地图矫正 | 地图打开时按 `E` |

世界时间通过画面上的“下一时间段”按钮推进。

### NPC 人物日志

靠近 NPC 后按 `E` 打开人物面板，可切换“人物概况”“日程记录”和“重要经历”。
日程页显示玩家已知的最近七日实际活动，经历页显示任务、关系、组织和后续战斗等
重要事件；校内公开记录、亲眼所见与传闻会标明不同来源，未知秘密不会显示。
人物日志按需分页读取，不会把 200 名 NPC 的完整历史放入地图快照。

### 物品与交易

按 `I` 打开文字灰盒交易面板。左侧选择商店，中间查看库存、营业状态与买卖价，
右侧查看玩家资金、负重和背包。当前按钮每次交易一件物品；打烊、资金不足、
库存不足、超重或合法性不符时不会发生部分扣款。

物品与商店数据位于 `content/items/`，详细规则见
[`design/ITEMS_AND_TRADING.md`](design/ITEMS_AND_TRADING.md)。

### 世界地图

- 鼠标滚轮或界面按钮：缩放地图。
- 鼠标右键/中键拖动：平移地图。
- 地图上的标记显示玩家当前位置。

### 地图矫正模式

- 左键绘制当前选择的地图类型。
- `Ctrl+Z`：撤销。
- `Ctrl+Y`：重做。
- `Ctrl+S`：保存，并同步更新正交蓝图和游戏地图。

矫正前建议单独备份地图数据。协作时尽量避免多人同时修改同一份地图布局文件。

## NPC 与世界时间

按 `Q` 打开人物名册后，可以：

- 浏览所有模拟 NPC。
- 查看人物状态、职业、记忆、愿望和当前计划。
- 查看由其分层外观组成的 idle 第一帧。
- 点击“到达这个人的位置”，传送到该 NPC 附近。

每名 NPC 会根据当前时段计划中的 `scene_id` 出现在对应地图区域。当前版本只改变人物出现位置，暂未实现 NPC 在地图上的连续动作和交互动画。

## LLM 接口

按 `Esc` 打开接口配置面板，可以新建并保存多个本地配置：

- `规则模式（离线）`：完全本地运行。
- `DeepSeek`：使用 DeepSeek API。
- `DeepSeek兼容接口`：连接采用同类请求格式的服务。
- `Ollama（本地）`：连接本机 Ollama 模型。

点击“保存并应用”只会切换接口，不会立即产生外部请求。所选接口会从下一个校园时段开始，仅在预算允许时用于深度 NPC 的合法候选选择。

默认仍为离线规则模式。当前硬限制为每时段最多 4 次、每游戏日最多 12 次、每日预估最多 24000 Token、单次输出最多 160 Token；接口异常或返回非法候选时自动回退规则决策。正式接口还必须填写服务方提供的 Base URL。

接口配置保存在 Godot 的：

```text
user://llm_interfaces.cfg
```

API Key 不会写入项目仓库，但该本地配置文件本身没有加密。不要提交密钥、`.env` 或 `config.local.json`。

模型名称与认知安全边界见 [`design/NPC_COGNITION_LLM_RUNTIME.md`](design/NPC_COGNITION_LLM_RUNTIME.md)。

详细说明见 [`game/SIMULATION_INTEGRATION.md`](game/SIMULATION_INTEGRATION.md)。

## 单独运行世界模拟

在仓库根目录执行离线模拟：

```powershell
python3 -m simulation --days 3 --llm rule
```

运行测试：

```powershell
python3 -m unittest discover -s tests -v
```

模拟产生的快照、人物日志和事件追踪会写入 `runs/`，该目录中的运行结果默认不提交 Git。

## 数据与确定性

- 相同的世界种子与 NPC ID 会产生相同人物外观。
- NPC 的公共场景到城市区域映射位于 `game/data/simulation/scene_regions.json`。
- 人物美术目录位于 `game/data/appearance_catalog.json`。
- 地图逻辑布局与人工修正数据位于 `game/data/maps/`。

修改数据结构时，应同步检查 Godot 桥接脚本与 Python 快照格式。

## 美术素材与许可

本协作仓库包含游戏运行所需的人物分层动画素材。项目所有者已确认素材作者允许项目协作者使用和通过本项目仓库共享。使用者仍须阅读并遵守：

```text
game/assets/characters/gandalf_hardcore/READ ME.txt
```

不要把人物素材从本项目中单独提取、重新打包、转售或用于原许可禁止的用途。

仅用于制作地图时参考、且游戏运行不需要的第三方地图截图未包含在仓库中。确定性地图蓝图、道路数据和临时 Tile 已保留。

## 协作约定

- 不提交 API Key、个人配置和本地接口文件。
- 不提交 `.godot/`、`__pycache__/`、`.import` 和运行日志。
- 新增 NPC 字段时，同时更新 Python 快照输出、Godot bridge 和人物详情 UI。
- 新增地图语义区域时，同时更新地图布局和 `scene_regions.json`。
- 提交前至少运行 Python 测试，并在 Godot 中启动一次主测试场景。

## 当前开发方向

- 约束式校园 NPC 生成、六项属性、人格与多维关系。
- 表世界论坛、NPC/玩家公平任务竞争、原子锁定与社会后果（第一版已实现）。
- 八学院能力、十二核心社团、课程和校园生活。
- 20 个 LLM 深度槽位与玩家最多 6 人的记名/觉醒系统。
- 夜相、污染、三排人物部署卡牌回合制与 NPC 后台战斗。
- 28 天四阶段主线、知识理解、动态参与者与多结局。

## 版本

当前重构分支入口：`game/` + `simulation/`；原 `project-a-0.2/` 与 `emergent_town_demo/` 保留。
