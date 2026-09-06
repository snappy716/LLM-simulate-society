extends RefCounted

const PENDING_MESSAGE := "正在处理，请等待结果。"
const NEED_NAMES := {
	"rest": "休息需求", "food": "饮食需求", "safety": "安全需求", "social": "社交需求",
	"money": "经济需求", "achievement": "成就需求", "curiosity": "求知需求", "commitment_pressure": "承诺压力",
}


static func operation_feedback(success: bool, response: Dictionary) -> String:
	# Preserve authoritative refusal/uncertain transport messages; never invent a result.
	if not success and not String(response.get("error", "")).is_empty():
		return String(response.error)
	var result: Variant = response.get("result", {})
	if result is Dictionary and not String(result.get("message", "")).is_empty():
		return String(result.message)
	return "操作已完成。" if success else "操作结果未确认，请刷新状态后再决定是否重试。"

const ACTIVITY_NAMES := {
	"ORIENTATION_OR_CLASS": "报到或上课",
	"RESEARCH": "研究",
	"TEACH": "授课",
	"COURSEWORK": "完成课程任务",
	"CLUB_ACTIVITY": "参加社团活动",
	"CAMPUS_EXPLORATION": "熟悉校园",
	"READ_OR_SOCIALIZE": "阅读或社交",
	"PERSONAL_ACTIVITY": "处理个人事务",
	"WORK": "工作",
	"PATROL": "巡逻",
	"REST": "休息",
	"ADMINISTRATION_SHIFT": "处理行政事务",
	"ASSIST_RESEARCH_OR_TEACHING": "协助研究或教学",
	"ATTEND_CLASS": "上课",
	"CAMPUS_SERVICE_SHIFT": "校园服务值班",
	"CASE_NOTES": "整理咨询记录",
	"CLUB_OR_PERSONAL_ACTIVITY": "参加社团或个人活动",
	"CLUB_OR_SELF_STUDY": "参加社团或自习",
	"COUNSELING_SHIFT": "心理咨询值班",
	"LAB_OR_SEMINAR": "实验或研讨",
	"LIBRARY_SHIFT": "图书馆值班",
	"LITERATURE_REVIEW": "阅读文献",
	"MAINTENANCE_SHIFT": "校园维修值班",
	"MEDICAL_SHIFT": "医疗值班",
	"NIGHT_SECURITY_SHIFT": "夜间安保值班",
	"ON_CALL_MAINTENANCE": "维修待命",
	"ON_CALL_MEDICAL_SHIFT": "医疗待命",
	"ON_CALL_SUPPORT": "值班待命",
	"OPTIONAL_RESEARCH": "自主研究",
	"PREPARE_MATERIALS": "准备教学材料",
	"PREPARE_OR_REVIEW": "备课或复盘",
	"RESEARCH_OR_OFFICE_HOURS": "研究或答疑",
	"SECURITY_PATROL": "校园巡逻",
	"SELF_STUDY": "自习",
	"SOCIAL_OR_SELF_STUDY": "社交或自习",
	"TEACH_CLASS": "授课",
}


static func activity_name(activity_id: String) -> String:
	return String(ACTIVITY_NAMES.get(activity_id, "其他活动")) if not activity_id.is_empty() else "暂无活动"


static func activity_status(status: String) -> String:
	return String({"completed": "已完成", "blocked": "未能完成"}.get(status, "尚无结果"))
