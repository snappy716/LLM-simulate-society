extends RefCounted

# Presentation only: keep commands and availability rules in their existing panels.
const GROUPS := [
	{"title": "校园生活", "entries": [
		{"id": "courses", "caption": "课程与知识", "icon": "leaderboardsComplex", "keywords": "上课学习"},
		{"id": "clubs", "caption": "活动与成员", "icon": "trophy", "keywords": "社团"},
		{"id": "market", "caption": "物品与购买", "icon": "shoppingCart", "keywords": "背包购物使用"},
		{"id": "health", "caption": "生命与恢复", "icon": "plus", "keywords": "治疗休息"},
		{"id": "album", "caption": "校园影像", "icon": "movie", "keywords": "照片"},
		{"id": "wallet", "caption": "余额与收支", "icon": "menuList", "keywords": "金钱"},
		{"id": "notes", "caption": "日程与记录", "icon": "menuList", "keywords": "日志"},
	]},
	{"title": "人物与世界", "entries": [
		{"id": "messages", "caption": "联系人与消息", "icon": "phone", "keywords": "聊天对话"},
		{"id": "assistance", "caption": "求助与履约", "icon": "share1", "keywords": "物资赠送承诺"},
		{"id": "party", "caption": "成员与协作", "icon": "multiplayer", "keywords": "组队"},
		{"id": "trade", "caption": "报价与交换", "icon": "share1", "keywords": "买卖交易"},
		{"id": "forums", "caption": "帖子与委托", "icon": "massiveMultiplayer", "keywords": "任务表世界里世界"},
		{"id": "combat", "caption": "阵容与指令", "icon": "target", "keywords": "卡牌战斗"},
	]},
	{"title": "系统", "entries": [
		{"id": "settings", "caption": "模型与连接", "icon": "gear", "keywords": "API LLM"},
		{"id": "saves", "caption": "保存与载入", "icon": "save", "keywords": "存档读档"},
	]},
]
