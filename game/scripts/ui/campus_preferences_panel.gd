extends VBoxContainer
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
var status: Label
var fullscreen: CheckButton
var revert: Timer
var confirm_display: ConfirmationDialog
var old_mode: Window.Mode
var probe: Button
var probe_status: Label
var probe_confirmation: ConfirmationDialog

func _ready() -> void:
	add_child(KIT.label("画面与声音", 20))
	fullscreen = CheckButton.new()
	fullscreen.text = "全屏显示 · 10 秒未确认自动恢复"
	fullscreen.button_pressed = get_window().mode in [Window.MODE_FULLSCREEN, Window.MODE_EXCLUSIVE_FULLSCREEN]
	fullscreen.toggled.connect(_change_display)
	add_child(fullscreen)
	confirm_display = KIT.confirmation(self, func(): revert.stop(); status.text = "本次会话的窗口模式已确认。")
	confirm_display.add_to_group("campus_settings_confirmation")
	confirm_display.canceled.connect(_restore_display)
	revert = Timer.new()
	revert.one_shot = true
	revert.wait_time = 10
	revert.timeout.connect(_restore_display)
	add_child(revert)
	add_child(KIT.label("帧率上限（低功耗 / 标准 / 高刷新）", 14))
	var fps := KIT.filter(["30 FPS", "60 FPS", "120 FPS"], func(index): _set_preference("fps", [30, 60, 120][index]))
	fps.select([30, 60, 120].find(CampusPreferences.values.fps))
	add_child(fps)
	add_child(KIT.label("正文默认字号 · 标题及紧凑专用控件保持设计字号", 14))
	var font := KIT.filter(["标准 · 16", "较大 · 18"], func(index): _set_preference("font_size", 16 if index == 0 else 18))
	font.select(0 if CampusPreferences.values.font_size == 16 else 1)
	add_child(font)
	add_child(KIT.label("游戏总音量 · 控制 Master 总线，不影响电脑其他应用", 14))
	var volume := HSlider.new()
	volume.min_value = 0
	volume.max_value = 1
	volume.step = 0.05
	volume.value = CampusPreferences.values.volume
	volume.value_changed.connect(func(value): _set_preference("volume", value))
	volume.custom_minimum_size.y = 32
	add_child(volume)
	for entry in [["muted", "游戏静音"], ["reduced_motion", "减少过夜动画运动（不缩短实际模型等待）"]]:
		var button := CheckButton.new()
		button.text = entry[1]
		button.button_pressed = CampusPreferences.values[entry[0]]
		button.toggled.connect(func(value): _set_preference(entry[0], value))
		add_child(button)
	status = KIT.label("偏好仅保存在本机，与 API 密钥及世界存档分开。", 14)
	add_child(status)
	add_child(KIT.label("模型与模拟状态", 20))
	probe = KIT.button("测试已应用的 API · 可能消耗额度", func(): KIT.ask(probe_confirmation, "将向当前已应用的模型发送一次短测试，不包含 NPC、聊天记录或存档。输出最多 128 Token，供应商仍可能计费。是否继续？"))
	add_child(probe)
	probe_confirmation = KIT.confirmation(self, func():
		if not SimulationBridge.connected or SimulationBridge.busy or SimulationBridge.is_campus_busy():
			probe_status.text = "本地服务未连接或正在处理，请恢复后再测试。"
			return
		probe.disabled = true
		probe_status.text = "正在测试已应用接口，不会自动重试……"
		SimulationBridge.probe_interface()
	)
	probe_confirmation.add_to_group("campus_settings_confirmation")
	probe_status = KIT.label("尚未发起测试。更改地址或模型后，请先在 API 管理页保存并应用。", 14)
	add_child(probe_status)
	SimulationBridge.interface_probe_completed.connect(_probe_completed)
	SimulationBridge.connection_state_changed.connect(func(connected, _message): probe.disabled = not connected or SimulationBridge.interface_probe_pending)
	if not SimulationBridge.last_interface_probe.is_empty(): _probe_completed(SimulationBridge.last_interface_probe)
	probe.disabled = SimulationBridge.interface_probe_pending or not SimulationBridge.connected
	var cognition: Dictionary = SimulationBridge.campus_snapshot.get("cognition", {})
	var usage: Dictionary = cognition.get("usage", {})
	add_child(KIT.label("本地模拟：%s\n模型：%s\n本世界记录：%d 次请求 · 输入 %d / 输出 %d Token\n估算 Token：%d（不与实报数相加）· 回退 %d 次\n统计随世界存档恢复，不等于 API 账户账单；供应商未报告的消耗可能不在实报数中。\n\nNPC 完整日程在过夜时规划；主动聊天可随时请求，不设每日次数上限。深度好友会增加后续自动调用。" % ["已连接" if SimulationBridge.connected else "未连接", cognition.get("provider", {}).get("model", "离线规则"), int(usage.get("calls", 0)), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), int(usage.get("estimated_tokens", 0)), int(usage.get("fallbacks", 0))], 14))

func _set_preference(key: String, value: Variant) -> void:
	CampusPreferences.values[key] = value
	var result := CampusPreferences.persist()
	status.text = "设置已保存。" if result == OK else "本次已生效，但保存失败；重启后可能恢复原值。"

func _probe_completed(result: Dictionary) -> void:
	probe.disabled = not SimulationBridge.connected
	var usage: Dictionary = result.get("aggregate_usage", {})
	probe_status.text = "%s\n%s\n接口测试累计 %d 次 · 输入 %d / 输出 %d Token\n%s" % [result.get("message", "结果待确认"), result.get("code", ""), int(usage.get("calls", 0)), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), result.get("scope", "未收到完整计量，不代表费用为零。")]

func _change_display(enabled: bool) -> void:
	old_mode = get_window().mode
	get_window().mode = Window.MODE_FULLSCREEN if enabled else Window.MODE_WINDOWED
	revert.start()
	KIT.ask(confirm_display, "保留此窗口显示模式？10 秒不确认将恢复。此设置仅用于本次会话。")

func _restore_display() -> void:
	revert.stop()
	confirm_display.hide()
	get_window().mode = old_mode
	fullscreen.set_pressed_no_signal(old_mode in [Window.MODE_FULLSCREEN, Window.MODE_EXCLUSIVE_FULLSCREEN])
	status.text = "已恢复原窗口模式。"

func _exit_tree() -> void:
	if revert != null and not revert.is_stopped(): get_window().mode = old_mode
