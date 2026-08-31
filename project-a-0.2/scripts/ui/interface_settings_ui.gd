extends CanvasLayer

const SETTINGS_PATH := "user://llm_interfaces.cfg"
const PROVIDERS := ["rule", "deepseek", "deepseek_compatible", "ollama"]

@onready var panel: Control = $Panel
@onready var profile_list: ItemList = $Panel/Window/ProfileList
@onready var profile_name: LineEdit = $Panel/Window/ProfileName
@onready var provider: OptionButton = $Panel/Window/Provider
@onready var base_url: LineEdit = $Panel/Window/BaseUrl
@onready var model: LineEdit = $Panel/Window/Model
@onready var api_key: LineEdit = $Panel/Window/ApiKey
@onready var status: Label = $Panel/Window/Status

var profiles: Array[Dictionary] = []
var selected_index := -1


func _ready() -> void:
	panel.visible = false
	for label in ["规则模式（离线）", "DeepSeek", "DeepSeek兼容接口", "Ollama（本地）"]:
		provider.add_item(label)
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
		panel.visible = not panel.visible
		if panel.visible:
			_load_profiles()
		get_viewport().set_input_as_handled()


func _load_profiles() -> void:
	profiles.clear()
	var config := ConfigFile.new()
	if config.load(SETTINGS_PATH) == OK:
		for section in config.get_sections():
			profiles.append({
				"name": config.get_value(section, "name", section),
				"provider": config.get_value(section, "provider", "rule"),
				"base_url": config.get_value(section, "base_url", ""),
				"model": config.get_value(section, "model", ""),
				"api_key": config.get_value(section, "api_key", ""),
			})
	if profiles.is_empty():
		profiles = [
			{"name": "离线规则", "provider": "rule", "base_url": "", "model": "", "api_key": ""},
			{"name": "DeepSeek", "provider": "deepseek", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "api_key": ""},
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
	_provider_changed(provider.selected)
	status.text = "配置仅保存在本机 user://"


func _add_profile() -> void:
	profiles.append({"name": "新接口", "provider": "deepseek_compatible", "base_url": "", "model": "", "api_key": ""})
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
	}
	_save_profiles()
	_rebuild_list()
	profile_list.select(selected_index)
	status.text = "正在应用接口……"
	$Panel/Window/SaveApply.disabled = true
	SimulationBridge.configure_interface(profiles[selected_index])


func _save_profiles() -> void:
	var config := ConfigFile.new()
	for index in range(profiles.size()):
		var section := "profile_%03d" % index
		for key in profiles[index]:
			config.set_value(section, key, profiles[index][key])
	var error := config.save(SETTINGS_PATH)
	if error != OK:
		status.text = "本地配置保存失败：%s" % error


func _provider_changed(index: int) -> void:
	var provider_id: String = PROVIDERS[index]
	var offline: bool = provider_id == "rule"
	base_url.editable = not offline
	model.editable = not offline
	api_key.editable = provider_id in ["deepseek", "deepseek_compatible"]
	if provider_id == "ollama":
		api_key.text = ""


func _interface_configured(success: bool, result: Dictionary) -> void:
	$Panel/Window/SaveApply.disabled = false
	status.text = String(result.get("message", "接口已应用")) if success else "应用失败：%s" % result.get("error", "未知错误")


func _close() -> void:
	panel.visible = false
