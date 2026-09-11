extends SceneTree
const KIT := preload("res://scripts/ui/campus_ui_kit.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	create_timer(110).timeout.connect(func(): push_error("system menu timeout"); quit(1))
	var bridge := root.get_node("SimulationBridge")
	var menu := root.get_node("SystemMenu")
	change_scene_to_file(String(ProjectSettings.get_setting("application/run/main_scene")))
	for _i in range(400):
		if bridge.connected and menu._pending.is_empty() and menu.page == "home": break
		await create_timer(0.05).timeout
	assert(menu.title_mode and menu.is_open() and paused)
	assert(menu.buttons.continue.disabled and not menu.buttons.new.disabled)
	assert(menu.buttons.continue.tooltip_text.contains("无可继续"))
	var revision: int = bridge.campus_snapshot.revision
	bridge.advance_social_pulse()
	assert(not bridge.is_campus_busy(), "title must not progress NPC attention")
	for size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = size
		for _i in range(3): await process_frame
		assert(menu.overlay.get_global_rect().encloses(menu.back.get_global_rect()))
		menu._new_page()
		menu._confirm("new")
		assert(menu.confirmation.visible)
		assert(menu.confirmation.get_cancel_button().has_focus())
		menu.confirmation.hide()
		menu.confirmation.canceled.emit()
		assert(bridge.campus_snapshot.revision == revision, "cancel cannot reset world")
		menu._back()
	menu._new_page()
	menu._confirm("new")
	menu.confirmation.hide()
	menu._confirmed()
	var created = await bridge.campus_persistence_completed
	assert(created[0] and created[1].operation == "new")
	for _i in range(12): await process_frame
	assert(current_scene.has_node("CampusHUD"))
	assert(menu.page == "guide" and menu.is_open() and paused)
	assert(bridge.campus_snapshot.clock.day == 1)
	menu._back()
	assert(not menu.is_open() and not paused)
	var escape := InputEventAction.new()
	escape.action = "ui_cancel"
	escape.pressed = true
	menu._input(escape)
	assert(menu.is_open() and not menu.title_mode and paused)
	assert(not current_scene.get_node("CampusHUD").visible)
	menu._settings()
	menu.buttons.api.pressed.emit()
	var settings := root.get_node("InterfaceSettings")
	assert(settings.is_open())
	settings._close()
	assert(menu.is_open() and paused, "settings must return to paused caller")
	assert(menu.buttons.api.has_focus())
	menu._back()
	menu._save_page()
	await bridge.campus_persistence_completed
	var saves: VBoxContainer = menu.body.get_child(0)
	assert(not saves.read_only and not saves.save_button.disabled)
	saves._prepare("save", false)
	saves.confirmation.hide()
	saves._confirm()
	var saved = await bridge.campus_persistence_completed
	assert(saved[0] and saved[1].slots[0].current.compatible)
	assert(saves.detail.text.contains("初检兼容"))
	menu._back()
	menu._confirm("title")
	menu.confirmation.hide()
	menu._confirmed()
	for _i in range(10): await process_frame
	for _i in range(200):
		if menu._pending.is_empty(): break
		await create_timer(0.05).timeout
	assert(menu.title_mode and paused)
	menu._ever_played = false # Cold-start continue fixture, with a real saved slot.
	menu._update_availability()
	assert(not menu.buttons.continue.disabled)
	menu._continue()
	var loaded = await bridge.campus_persistence_completed
	assert(loaded[0] and loaded[1].operation == "load")
	for _i in range(8): await process_frame
	assert(not menu.is_open() and not paused and current_scene.has_node("CampusHUD"))
	assert(current_scene.get_node("CampusHUD").visible)
	menu.open_pause()
	menu._confirm("quit")
	assert(menu.confirmation.visible)
	menu.confirmation.hide()
	menu.confirmation.canceled.emit()
	assert(menu.is_open(), "cancel exit must preserve session")
	# Common components: state vocabulary and actual callbacks, not fake data.
	var probe := VBoxContainer.new()
	root.add_child(probe)
	for state in ["loading", "empty", "disabled", "error", "unconfirmed", "success"]:
		var label := KIT.status("测试", state)
		probe.add_child(label)
		assert(label.text != "测试")
	var calls := []
	var search := KIT.search("搜索", func(value): calls.append(value))
	probe.add_child(search)
	search.text_changed.emit("校园")
	var tabs := KIT.tabs(["概况", "记录"], func(value): calls.append(value))
	probe.add_child(tabs)
	tabs.current_tab = 1
	var pager := KIT.pagination(0, 2, func(value): calls.append(value))
	probe.add_child(pager)
	assert(pager.get_child(0).disabled and not pager.get_child(2).disabled)
	pager.get_child(2).pressed.emit()
	assert(calls == ["校园", 1, 1])
	probe.queue_free()
	print("CAMPUS_SYSTEM_MENU_OK title new_confirm cancel new_world guide pause settings save compatible_continue return_title quit_cancel three_sizes components no_paid_api")
	quit(0)
