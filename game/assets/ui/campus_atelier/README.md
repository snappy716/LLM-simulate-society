# 月下校园 UI 美术 · 第一批

2026-09-11。只补界面视觉，不改变玩法、角色身份、地图布局、关系或 LLM 规则。

## 文件与接入

| 文件 | 用途 | 来源 |
| --- | --- | --- |
| moon_lake_v1.png | 标题页静态月湖氛围图，1536×1024；不是新增可探索场景 | 本轮内置 imagegen 生成，提示词见下 |
| icons/*.svg | 16 个手机应用图标 + knowledge/support/character/anomaly 4 个战斗语义图标；64×64 透明画布 | 本项目原生 SVG 绘制 |
| card_idle.svg / card_active.svg | 卡牌普通/高亮边饰，九宫格拉伸，256×320 | 本项目原生 SVG 绘制 |

配色：亮白 #f5fbff、清蓝 #48c2ff、冰蓝 #8cddff、墨蓝 #102d43。以简单功能轮廓为主，天文元素只放在标题和夜相/知识语义上，手机内部没有月亮壁纸，也不替换用户确认的六枚常驻 HUD 图标。

接入点：campus_system_menu.gd、campus_phone_ui.gd、campus_battle_screen.gd、campus_growth_panel.gd；共同资源入口 campus_ui_art.gd。卡牌效果图标依据已公开 effect_ids 选择，只表达支援/攻击/知识大类，不代替规则说明或代表额外技能。人物标识为通用图形，不是生成的人物头像；异常标识不是每种敌人的最终立绘。

## 素材与参考边界

- 图像由内置 imagegen 生成，未调用游戏配置中的个人 DeepSeek API；没有使用 CLI/API 图像生成路径。
- [P3R 官方页面](https://persona.atlus.com/p3r/index.html?lang=en)仅作为蓝色调与视觉留白的参考，不下载或复制其角色、图标、标志及构图。
- 旧 [Kenney 图标](https://kenney.nl/assets/game-icons)及许可证保留，部分通用控件继续沿用；本目录的原创/生成素材不冒称来自 Kenney，也不套用它的 CC0 标签。
- 原七张校园地图、协作者场景、美术和现有 HUD 源文件未删除、未覆盖。
- 图像作为静态资源载入；不新增屏幕模糊、全屏粒子、逐帧图像生成或 LLM 请求。新增大图解码像素预算约 6 MiB（RGBA8 估算，不是整机显存实测）。
- 新 UI 素材控件采用平滑采样；不修改项目全局采样或校园场景的像素显示方式。卡框使用缓存的九宫格样式，装饰图形不拦截点击。
- 后续替换图像保持路径或在共同入口改引用；SVG 保持 viewBox 与透明背景。文字始终由 Godot 绘制，不能烘进卡面后丢失费用、状态与本地化。

## imagegen 最终提示词

工具模式：内置工具。生成原图已复制进本目录，项目不依赖工作区外路径。

```text
Use case: stylized-concept. Asset type: original game UI atmospheric background illustration, landscape 1536x1024. Primary request: a restrained luminous blue moon reflected in a university lake, a single slender orbital arc crosses the moon reflection, the intersection suggesting two worlds and human connections. Modern Chinese university mystery life simulation, psychology and moonlight anomalies, tranquil but uncanny, sophisticated editorial game art, clean painterly screen print with restrained fine grain. Composition: mostly quiet deep ink blue and cerulean negative space across left two thirds for real UI text; moon and moon reflection in right third, subtle distant dark campus roof silhouettes at bottom edge only, not a new explorable map, no real identifiable university landmarks. Color palette luminous ice white, clear cyan #48c2ff, lake blue #12669e, deep ink #102438. Bright crisp moon, restrained pale horizon, not a black muddy image; soft mist and few sparse points, no busy stars. No characters, no words, no typography, no icons, no logos, no UI controls, no borders, no collage, no watermark. Original illustration, not copying any existing game composition. Final asset intended for title menu and small banner crops, all interaction and labels supplied by engine.
```
