# 青春校园 UI 美术 · 第二批（2026-09-11）

## 当前方向

现代中国大学的日常生活，明亮、写实、蓝白界面。校园建筑的红砖、连廊、钟楼、远山与绿树作为视觉参考；天文元素可选，不能在主视觉中提前确定尚未敲定的剧情。界面文字保持引擎渲染。

## 雁栖湖校区参考索引

- [中科院建筑设计研究院作品介绍（ARCHINA）](https://www.archina.com/index.php?a=show&g=Works&id=157711&m=index)：参考红砖、钟楼、庭院与步行景观的组织；资料描述轴线与景观带并存。
- [光影国科大：2025 春雪](https://news.ucas.ac.cn/gygkd/b1b3c3969451487b817955dc4013b25f.htm)：参考建筑、咖啡厅、路牌等日常细节；不采用冬雪作为当前封面季节。
- [那年今日那些人](https://news.ucas.ac.cn/xydt/722a0d0707a641cdbcbf4860611c3e04.htm)：参考学生生活和校园公交站的生活尺度。
- [安德的影子_：雁栖湖校区全年航拍](https://www.bilibili.com/video/BV19T41137ND)：公开个人视频参考索引，作者标注未经授权禁止转载。
- [玥迹信箱：校园写真合集](https://www.bilibili.com/s/video/BV15f4y1f7Ct)：公开个人摄影参考索引，作者标注未经授权禁止转载。
- [教学空间案例（圣奥）](https://www.isunon.com/health/detail/648.html)：参考自然光、可组合桌椅与校园学习空间。

本轮查阅公开检索结果、图片索引和可访问文章；部分大图/浏览器加载超时，未完整播放个人视频，不将其描述为逐帧审阅。用户此前提供的校门照片也是视觉参考。没有下载或打包上述第三方照片、视频；不提取真人肖像，不使用学校校名、校徽和其他识别标志。生成画面为虚构校园，不声称是国科大实景复刻。

## 已制作及接入范围

| 资源 | 实际用途 |
| --- | --- |
| campus_day_v3.png | 明亮红砖钟楼校园封面；开始菜单浅色按钮与深蓝文字 |
| study_day_v3.png | 学习、笔记、卡牌库页眉的写实学习桌面氛围 |
| social_day_v3.png | 通讯、关系、社团、小队页眉的写实校园社交氛围 |
| 65 枚统一 SVG（原 20 + 新增 45） | 保留手机应用，补足地点、学院、时段、物品、友情/恋爱、卡牌效果、导航与通用状态图形 |
| 公共主题 | 将近黑面板提亮为校园蓝；保留可读的白色文字与焦点/禁用差异 |
| 过夜动效 | 用简洁钟表替代中心月牙；真实过夜请求和减少动态效果设置不变 |
| HUD 卡牌/关系 | 去除月牙依赖，保留原来的位置、尺寸和操作 |

实际绑定：手机页眉与应用入口、七张地图地点按钮、NPC 学院标识、日程四时段、物品分类、关系类型、卡牌效果、返回/关闭/保存/确认按钮。通用状态/搜索/筛选等部分图形先作为资源备齐，未强制插入每一处文本提示。未知学院/效果仍使用通用图标，不虚构状态。

封面和三类生活图片是 UI 装饰，不是新可行走地图；原有七张地图、碰撞、NPC 行走和业务规则没有改动。人物最终立绘、怪物原画、每张技能专属插画和战斗动作不在本批完成范围。

## 保存与替换

三张最终 PNG 及 SVG 均位于本目录。项目引用只使用 res:// 路径。旧 moon_lake_v1.png 保留为历史稿，不再用作活动封面。此次未采用的 v2 草稿移至仓库外的 ../output/ui-art-drafts-20260911/，可恢复，不上传。

图像使用 **内置 imagegen** 生成；用户已同意不指定模型。本工具不提供具体型号选择，因此不宣称采用 gpt-image-2 或 image-2.5。没有使用游戏个人 API。每张 1536×1024；三张 RGBA8 解码合计约 18 MiB（估算，非整机显存实测），按需加载，既有资源缓存由引擎管理；不新增逐帧生成或模型调用。

## 最终提示词

### 封面

```text
Use case: photorealistic-natural. Asset: 1536x1024 landscape main menu cover for a modern youthful Chinese university life game. Original fictional campus visually inspired by publicly documented UCAS Yanqi Lake campus architecture: coherent warm terracotta RED BRICK academic buildings with narrow tall windows, one slender rectangular brick clock tower with an ordinary white clock face in the right third, a glazed pedestrian connecting corridor with brick piers, low wooded northern Beijing mountain ridgeline in the distance, a generous pedestrian avenue, small lawns and summer trees. NOT generic beige American campus or medieval gothic school. Street-level 35mm architectural photograph, entirely realistic brick, glazing, pavement and foliage, midday to late-morning fresh natural sunlight, luminous blue sky and soft white clouds. Four small adult university students casually walking on the right path, backpacks, ordinary casual clothing, viewed from behind; credible anatomy. Composition: clock tower and main building in right half, left 40 percent quiet open pale-blue sky above a calm sunlit pale pavement and low lawn, usable as menu text negative space; compose subjects in middle 70% vertical frame to survive 16:9 cover cropping. Warm brick contrasts with crisp sky-blue, leafy green and cream. No moon, fantasy, astronomy symbols, eerie mood, darkness, vignette, painted/anime/3D-render look. No real school name, emblems, insignia, banners, recognizable people, logos, watermark, or any text. This is an original fictional campus promotional image, not an exact reconstruction or actual photograph of UCAS.
```

### 学习

```text
Use case: photorealistic-natural. Asset: 1536x1024 landscape editorial photograph for university game UI. Real sunlit wooden library study desk beside a bright window, blue cloth notebook, two plain textbooks with no lettering, a pen and one green ginkgo leaf bookmark. Natural daylight, realistic paper edges, fabric weave and soft leaf shadows, 50mm lens. Most objects on right third and in central horizontal band to survive a wide banner crop; left half clean bright tabletop for UI heading. Fresh cream white, gentle leaf green, sky blue; academic and contemporary. No people, no text, no logos, no watermark, no moon or stars, no conspiracy diagram. NOT an illustration, not anime or a 3D render, no unnatural exaggerated bokeh.
```

### 社交

```text
Use case: photorealistic-natural. Asset: 1536x1024 landscape editorial photograph for contemporary university game UI. Ordinary outdoor campus cafe table under green trees on a sunny afternoon. Two plain takeaway drinks, folded blank club handouts, a navy canvas bag hanging on a chair, modern red-brick university building softly out of focus behind. Real cardboard, cotton and wood textures, natural soft daylight, 50mm lens, photographic believable everyday scene. Right third holds objects, central horizontal band contains cups and flyers so they remain legible in a banner crop; left half calm pale tabletop. Warm cream and sky blue with restrained green. No people, no legible writing, no brands, no watermark, no moon or stars. Not anime, not painting, not 3D, not luxury advertising.
```
