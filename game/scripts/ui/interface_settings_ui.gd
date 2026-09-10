extends CanvasLayer

const SETTINGS_PATH := "user://llm_interfaces.cfg"
const PROVIDERS := ["rule", "openai_compatible", "ollama"]
const THINKING_MODES := ["auto", "default", "disabled", "enabled"]

@onready var panel: Control = $Panel
@onready var profile_list: ItemList = $Panel/Window/ProfileList
@onready var profile_name: LineEdit = $Panel/Window/ProfileName
@onready var provider: OptionButton = $Panel/Window/Provider
@onready var base_url: LineEdit = $Panel/Window/BaseUrl
@onready var model: LineEdit = $Panel/Window/Model
@onready var api_key: LineEdit = $Panel/Window/ApiKey
@onready var status: Label = $Panel/Window/Status
@onready var thinking: OptionButton = $Panel/Window/Thinking
@onready var request_timeout: SpinBox = $Panel/Window/RequestTimeout
@onready var request_concurrency: SpinBox = $Panel/Window/RequestConcurrency

var profiles: Array[Dictionary] = []
var selected_index := -1
var _paused_before_open := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("interface_settings_ui")
	panel.visible = false
	for label in ["规则模式（离线）", "OpenAI 兼容接口", "Ollama（本地）"]:
		provider.add_item(label)
	for label in ["自动适配", "服务默认", "关闭思考", "开启思考"]:
		thinking.add_item(label)
	thinking.tooltip_text = "自动：官方 DeepSeek V4 使用非思考模式；其他兼容服务不添加私有参数。显式开关要求服务支持 thinking 参数。"
	request_concurrency.tooltip_text = "过夜同时请求数，默认 10。只并行互不影响的日程，不增加请求总数或限制聊天次数。遇到服务限流可调低；本地 Ollama 保持串行。"
	profile_list.item_selected.connect(_select_profile)
	$Panel/Window/Add.pressed.connect(_add_profile)
	$Panel/Window/Delete.pressed.connect(_delete_profile)
	$Panel/Window/SaveApply.pressed.connect(_save_and_apply)
	$Panel/Window/Close.pressed.connect(_close)
	provider.item_selected.connect(_provider_changed)
	SimulationBridge.interface_configured.connect(_interface_configured)
	_load_profiles()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if panel.visible:
			_close()
		else:
			for group_name in ["campus_phone_ui", "campus_map_ui", "campus_npc_inspector_ui"]:
				var other := get_tree().get_first_node_in_group(group_name)
				if other != null and other.is_open():
					return
			open_settings()
		get_viewport().set_input_as_handled()


func is_open() -> bool:
	return panel != null and panel.visible


func open_settings() -> void:
	if is_open():
		return
	_paused_before_open = get_tree().paused
	_load_profiles()
	panel.visible = true
	get_tree().paused = true
	var current: Dictionary = SimulationBridge.campus_snapshot.get("cognition", {}).get("provider", {})
	var last: Dictionary = current.get("last_result", {})
	var labels := {"untested": "尚未验证", "received": "已收到响应，待校验", "accepted": "最近响应已通过校验", "failed": "最近请求失败"}
	var errors := {"output_truncated": "输出被截断，请关闭思考或调整模型", "timeout": "模型请求超时", "invalid_json": "响应不是合法 JSON", "http_401": "密钥验证失败", "http_402": "账户余额不足"}
	var error_code := str(last.get("error_code", ""))
	status.text = "当前：%s · %s\n%s" % [current.get("model", "离线"), labels.get(last.get("state", "untested"), "待核对"), errors.get(error_code, error_code)]


func _settings_path() -> String:
	var override_path := OS.get_environment("GODOT_SIM_SETTINGS_PATH")
	return SETTINGS_PATH if override_path.is_empty() else override_path


func _load_profiles() -> void:
	profiles.clear()
	var config := ConfigFile.new()
	if config.load(_settings_path()) == OK:
		for section in config.get_sections():
			profiles.append({
				"name": config.get_value(section, "name", section),
				"provider": _normalize_provider_id(String(config.get_value(section, "provider", "rule"))),
				"base_url": config.get_value(section, "base_url", ""),
				"model": config.get_value(section, "model", ""),
				"api_key": config.get_value(section, "api_key", ""),
				"thinking_mode": config.get_value(section, "thinking_mode", "auto"),
				"timeout_seconds": config.get_value(section, "timeout_seconds", 30.0),
				"max_concurrent_requests": config.get_value(section, "max_concurrent_requests", 10),
			})
	if profiles.is_empty():
		profiles = [
			{"name": "离线规则", "provider": "rule", "base_url": "", "model": "", "api_key": ""},
			{"name": "通用兼容接口", "provider": "openai_compatible", "base_url": "", "model": "", "api_key": ""},
			{"name": "本地 Ollama", "provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen3:8b", "api_key": ""},
		]
	_rebuild_list()
	_select_profile(clampi(selected_index, 0, profiles.size() - 1))


func _rebuild_list() -> void:
	profile_list.clear()
	for item in profiles:
		profile_list.add_item("%s  ·  %s" % [item.name, item.provider])


func _select_profile(index: int) -> void:
	if index < 0 or index >= profiles.size():
		return
	selected_index = index
	profile_list.select(index)
	var item := profiles[index]
	profile_name.text = String(item.name)
	provider.select(maxi(0, PROVIDERS.find(String(item.provider))))
	base_url.text = String(item.base_url)
	model.text = String(item.model)
	api_key.text = String(item.api_key)
	thinking.select(maxi(0, THINKING_MODES.find(str(item.get("thinking_mode", "auto")))))
	request_timeout.value = float(item.get("timeout_seconds", 30.0))
	request_concurrency.value = int(item.get("max_concurrent_requests", 10))
	_provider_changed(provider.selected)
	status.text = "配置仅保存在本机 user://"


func _add_profile() -> void:
	profiles.append({"name": "新接口", "provider": "openai_compatible", "base_url": "", "model": "", "api_key": ""})
	_rebuild_list()
	_select_profile(profiles.size() - 1)


func _delete_profile() -> void:
	if selected_index < 0 or profiles.size() <= 1:
		status.text = "至少保留一个接口配置"
		return
	profiles.remove_at(selected_index)
	selected_index = clampi(selected_index, 0, profiles.size() - 1)
	_save_profiles()
	_rebuild_list()
	_select_profile(selected_index)


func _save_and_apply() -> void:
	if selected_index < 0:
		return
	var provider_id: String = PROVIDERS[provider.selected]
	profiles[selected_index] = {
		"name": profile_name.text.strip_edges() if not profile_name.text.strip_edges().is_empty() else "未命名接口",
		"provider": provider_id,
		"base_url": base_url.text.strip_edges(),
		"model": model.text.strip_edges(),
		"api_key": api_key.text.strip_edges(),
		"thinking_mode": THINKING_MODES[thinking.selected],
		"timeout_seconds": request_timeout.value,
		"max_concurrent_requests": int(request_concurrency.value),
	}
	if not _save_profiles():
		return
	_rebuild_list()
	profile_list.select(selected_index)
	status.text = "正在应用接口……"
	$Panel/Window/SaveApply.disabled = true
	SimulationBridge.configure_interface(profiles[selected_index])


func _save_profiles() -> bool:
	var config := ConfigFile.new()
	for index in range(profiles.size()):
		var section := "profile_%03d" % index
		for key in profiles[index]:
			config.set_value(section, key, profiles[index][key])
	var error := config.save(_settings_path())
	if error != OK:
		status.text = "本地配置保存失败：%s" % error
		return false
	return true


func _provider_changed(index: int) -> void:
	var provider_id: String = PROVIDERS[index]
	var offline: bool = provider_id == "rule"
	base_url.editable = not offline
	model.editable = not offline
	api_key.editable = provider_id == "openai_compatible"
	thinking.disabled = provider_id != "openai_compatible"
	request_timeout.editable = provider_id == "openai_compatible"
	request_concurrency.editable = provider_id == "openai_compatible"
	if provider_id == "ollama":
		api_key.text = ""


func _normalize_provider_id(provider_id: String) -> String:
	if provider_id in ["deepseek", "deepseek_compatible"]:
		return "openai_compatible"
	return provider_id if provider_id in PROVIDERS else "rule"


func _interface_configured(success: bool, result: Dictionary) -> void:
	$Panel/Window/SaveApply.disabled = false
	status.text = String(result.get("message", "接口已应用")) if success else "应用失败：%s" % result.get("error", "未知错误")
	if success and bool(result.get("status", {}).get("configured", false)):
		status.text = "接口已应用（尚未请求验证）\n%s · 思考：%s" % [result.get("model", ""), result.get("status", {}).get("thinking_mode", "default")]


func _close() -> void:
	panel.visible = false
	get_tree().paused = _paused_before_open
