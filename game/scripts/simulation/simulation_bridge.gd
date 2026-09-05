extends Node

signal snapshot_updated(snapshot: Dictionary)
signal connection_state_changed(connected: bool, message: String)
signal advance_state_changed(busy: bool)
signal interface_configured(success: bool, result: Dictionary)
signal trade_completed(success: bool, result: Dictionary)
signal item_use_completed(success: bool, result: Dictionary)
signal action_completed(success: bool, result: Dictionary)
signal campus_snapshot_updated(snapshot: Dictionary)
signal campus_traversal_completed(success: bool, result: Dictionary, passage_id: String)
signal campus_phase_advanced(success: bool, result: Dictionary)
signal campus_fast_travel_completed(success: bool, result: Dictionary, destination_id: String)
signal campus_task_operation_completed(success: bool, result: Dictionary, action_id: String, task_id: String)
signal campus_club_operation_completed(success: bool, result: Dictionary, action_id: String, club_id: String)
signal campus_party_operation_completed(success: bool, result: Dictionary, action_id: String, target_id: String)
signal campus_combat_operation_completed(success: bool, result: Dictionary, action_id: String, battle_id: String)
signal campus_cognition_operation_completed(success: bool, result: Dictionary, action_id: String, target_id: String)
signal campus_phone_message_completed(success: bool, result: Dictionary, action_id: String, target_id: String)
signal campus_dialogue_completed(success: bool, result: Dictionary, target_id: String)
signal campus_social_proposal_completed(success: bool, result: Dictionary, target_id: String, proposal_type: String)
signal campus_social_proposal_response_completed(success: bool, result: Dictionary, proposal_id: String)
signal campus_night_world_operation_completed(success: bool, result: Dictionary, action_id: String)
signal campus_npc_chronicle_loaded(success: bool, result: Dictionary, npc_id: String, filter_name: String)
signal campus_inventory_operation_completed(success: bool, result: Dictionary)

const SERVER_SCRIPT := "res://tools/simulation/godot_simulation_server.py"

var snapshot: Dictionary = {}
var server_pid := -1
var connected := false
var busy := false
var _request: HTTPRequest
var _campus_request: HTTPRequest
var _chronicle_request: HTTPRequest
var _retry_timer: Timer
var _pending_operation := ""
var campus_snapshot: Dictionary = {}
var _campus_busy := false
var _campus_pending_operation := ""
var _campus_pending_passage_id := ""
var _campus_pending_destination_id := ""
var _campus_pending_task_id := ""
var _campus_pending_task_action := ""
var _campus_pending_club_id := ""
var _campus_pending_club_action := ""
var _campus_pending_party_target_id := ""
var _campus_pending_party_action := ""
var _campus_pending_combat_battle_id := ""
var _campus_pending_combat_action := ""
var _campus_pending_cognition_target_id := ""
var _campus_pending_cognition_action := ""
var _campus_pending_message_target_id := ""
var _campus_pending_message_action := ""
var _campus_pending_dialogue_target_id := ""
var _campus_pending_proposal_target_id := ""
var _campus_pending_proposal_type := ""
var _campus_pending_proposal_id := ""
var _campus_pending_night_action := ""
var _campus_command_counter := 0
var _chronicle_busy := false
var _chronicle_npc_id := ""
var _chronicle_filter := "recent"
var _server_port := 8765
var _base_url := ""


func _ready() -> void:
	# Phone/map overlays pause the scene tree, but local HTTP commands must still
	# finish so task claims and other UI actions cannot deadlock.
	process_mode = Node.PROCESS_MODE_ALWAYS
	var configured_port := OS.get_environment("GODOT_SIM_PORT")
	if not configured_port.is_empty() and configured_port.is_valid_int():
		_server_port = clampi(int(configured_port), 1024, 65535)
	_base_url = "http://127.0.0.1:%d" % _server_port
	_request = HTTPRequest.new()
	_request.timeout = 180.0
	_request.request_completed.connect(_on_request_completed)
	add_child(_request)
	_campus_request = HTTPRequest.new()
	_campus_request.timeout = 30.0
	_campus_request.request_completed.connect(_on_campus_request_completed)
	add_child(_campus_request)
	_chronicle_request = HTTPRequest.new()
	_chronicle_request.timeout = 30.0
	_chronicle_request.request_completed.connect(_on_chronicle_request_completed)
	add_child(_chronicle_request)
	_retry_timer = Timer.new()
	_retry_timer.wait_time = 1.0
	_retry_timer.timeout.connect(_request_snapshot)
	add_child(_retry_timer)
	_start_server()
	_retry_timer.start()
	_request_snapshot()


func _exit_tree() -> void:
	if server_pid > 0:
		OS.kill(server_pid)


func advance_time() -> void:
	if busy or not connected:
		return
	busy = true
	advance_state_changed.emit(true)
	_pending_operation = "step"
	var error := _request.request(_base_url + "/step", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, "{}")
	if error != OK:
		_finish_with_error("无法发送时间推进请求：%s" % error)


func is_campus_busy() -> bool:
	return _campus_busy


func configure_interface(config: Dictionary) -> void:
	if busy or not connected:
		interface_configured.emit(false, {"error": "模拟服务尚未连接或正在推进"})
		return
	busy = true
	_pending_operation = "configure"
	var body := JSON.stringify(config)
	var error := _request.request(_base_url + "/configure", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
	if error != OK:
		busy = false
		interface_configured.emit(false, {"error": "无法发送接口配置：%s" % error})


func trade(shop_id: String, item_id: String, direction: String, quantity: int = 1) -> void:
	if busy or not connected:
		trade_completed.emit(false, {"trade": {"message": "模拟服务尚未连接或正在处理其他行动"}})
		return
	busy = true
	_pending_operation = "trade"
	var body := JSON.stringify({
		"actor_id": "player",
		"shop_id": shop_id,
		"item_id": item_id,
		"direction": direction,
		"quantity": quantity,
	})
	var error := _request.request(_base_url + "/trade", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
	if error != OK:
		busy = false
		trade_completed.emit(false, {"trade": {"message": "无法发送交易请求：%s" % error}})


func use_item(item_id: String) -> void:
	if busy or not connected:
		item_use_completed.emit(false, {"item_use": {"message": "模拟服务尚未连接或正在处理其他行动"}})
		return
	busy = true
	_pending_operation = "use_item"
	var body := JSON.stringify({"actor_id": "player", "item_id": item_id})
	var error := _request.request(_base_url + "/use-item", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
	if error != OK:
		busy = false
		item_use_completed.emit(false, {"item_use": {"message": "无法发送物品使用请求：%s" % error}})


func perform_action(action_id: String, parameters: Dictionary = {}) -> void:
	if busy or not connected:
		action_completed.emit(false, {"action": {"message": "模拟服务尚未连接或正在处理其他行动"}})
		return
	busy = true
	_pending_operation = "action"
	var payload := parameters.duplicate(true)
	payload["actor_id"] = String(payload.get("actor_id", "player"))
	payload["action_id"] = action_id
	var error := _request.request(
		_base_url + "/action", PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST, JSON.stringify(payload))
	if error != OK:
		busy = false
		action_completed.emit(false, {"action": {"message": "无法发送行动请求：%s" % error}})


func refresh_campus_snapshot() -> void:
	if _campus_busy or not connected:
		return
	_campus_busy = true
	_campus_pending_operation = "snapshot"
	var error := _campus_request.request(_base_url + "/kernel/campus-snapshot")
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""


func traverse_campus_passage(passage_id: String) -> void:
	if passage_id.is_empty():
		campus_traversal_completed.emit(false, {"error": "入口未配置 passage_id"}, passage_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_traversal_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他移动"}, passage_id)
		return
	_campus_busy = true
	_campus_pending_operation = "traverse"
	_campus_pending_passage_id = passage_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-campus-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "TRAVERSE_LOCATION_PASSAGE",
		"target_ids": [],
		"parameters": {"passage_id": passage_id},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_passage_id = ""
		campus_traversal_completed.emit(false, {"error": "无法发送校园移动请求：%s" % error}, passage_id)


func advance_campus_phase() -> void:
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_phase_advanced.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"})
		return
	_campus_busy = true
	_campus_pending_operation = "advance_phase"
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-phase-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "ADVANCE_PHASE",
		"target_ids": [],
		"parameters": {},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		campus_phase_advanced.emit(false, {"error": "无法发送时段推进请求：%s" % error})


func fast_travel_campus(destination_id: String) -> void:
	if destination_id.is_empty():
		campus_fast_travel_completed.emit(false, {"error": "校园地图没有指定目的地"}, destination_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_fast_travel_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他移动"}, destination_id)
		return
	_campus_busy = true
	_campus_pending_operation = "fast_travel"
	_campus_pending_destination_id = destination_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-map-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "FAST_TRAVEL_CAMPUS",
		"target_ids": [],
		"parameters": {"destination_id": destination_id},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_destination_id = ""
		campus_fast_travel_completed.emit(false, {"error": "无法发送校园地图移动请求：%s" % error}, destination_id)


func operate_campus_task(action_id: String, task_id: String, expected_task_revision: int = -1) -> void:
	if task_id.is_empty():
		campus_task_operation_completed.emit(false, {"error": "未指定论坛任务"}, action_id, task_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_task_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"}, action_id, task_id)
		return
	_campus_busy = true
	_campus_pending_operation = "task"
	_campus_pending_task_id = task_id
	_campus_pending_task_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var parameters := {"task_id": task_id}
	if expected_task_revision >= 0:
		parameters["expected_task_revision"] = expected_task_revision
	var command := {
		"command_id": "godot-task-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [],
		"parameters": parameters,
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_task_id = ""
		_campus_pending_task_action = ""
		campus_task_operation_completed.emit(false, {"error": "无法发送论坛任务请求：%s" % error}, action_id, task_id)


func operate_campus_club(action_id: String, club_id: String) -> void:
	if club_id.is_empty():
		campus_club_operation_completed.emit(false, {"error": "未指定社团"}, action_id, club_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_club_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"}, action_id, club_id)
		return
	_campus_busy = true
	_campus_pending_operation = "club"
	_campus_pending_club_id = club_id
	_campus_pending_club_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var player: Dictionary = campus_snapshot.get("player", {})
	var parameters := {"club_id": club_id}
	if action_id in ["CLUB_ACTIVITY", "CLUB_OR_PERSONAL_ACTIVITY", "CLUB_OR_SELF_STUDY"]:
		parameters["location_id"] = String(player.get("current_location_id", ""))
	var command := {
		"command_id": "godot-club-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [],
		"parameters": parameters,
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_club_id = ""
		_campus_pending_club_action = ""
		campus_club_operation_completed.emit(false, {"error": "无法发送社团请求：%s" % error}, action_id, club_id)


func operate_campus_party(action_id: String, target_id: String = "") -> void:
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_party_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"}, action_id, target_id)
		return
	_campus_busy = true
	_campus_pending_operation = "party"
	_campus_pending_party_target_id = target_id
	_campus_pending_party_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var parameters := {}
	if not target_id.is_empty():
		parameters["target_id"] = target_id
	var command := {
		"command_id": "godot-party-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [],
		"parameters": parameters,
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_party_target_id = ""
		_campus_pending_party_action = ""
		campus_party_operation_completed.emit(false, {"error": "无法发送组队请求：%s" % error}, action_id, target_id)


func operate_campus_inventory(action_id: String, parameters: Dictionary = {}) -> void:
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_inventory_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"})
		return
	_campus_busy = true
	_campus_pending_operation = "inventory"
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-inventory-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player", "action_id": action_id, "target_ids": [],
		"parameters": parameters.duplicate(true),
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)), "issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)), "source": "player",
	}
	var error := _campus_request.request(_base_url + "/kernel/command", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, JSON.stringify(command))
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		campus_inventory_operation_completed.emit(false, {"error": "无法发送校园物品请求：%s" % error})


func operate_campus_combat(action_id: String, parameters: Dictionary = {}) -> void:
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_combat_operation_completed.emit(
			false, {"error": "校园模拟尚未连接或正在处理其他行动"},
			action_id, String(parameters.get("battle_id", ""))
		)
		return
	_campus_busy = true
	_campus_pending_operation = "combat"
	_campus_pending_combat_battle_id = String(parameters.get("battle_id", ""))
	_campus_pending_combat_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-combat-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [],
		"parameters": parameters.duplicate(true),
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_combat_battle_id = ""
		_campus_pending_combat_action = ""
		campus_combat_operation_completed.emit(
			false, {"error": "无法发送战斗准备请求：%s" % error},
			action_id, String(parameters.get("battle_id", ""))
		)


func operate_campus_cognition(action_id: String, target_id: String) -> void:
	if target_id.is_empty():
		campus_cognition_operation_completed.emit(false, {"error": "未指定人物"}, action_id, target_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_cognition_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他行动"}, action_id, target_id)
		return
	_campus_busy = true
	_campus_pending_operation = "cognition"
	_campus_pending_cognition_target_id = target_id
	_campus_pending_cognition_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-cognition-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [target_id],
		"parameters": {"target_id": target_id},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_cognition_target_id = ""
		_campus_pending_cognition_action = ""
		campus_cognition_operation_completed.emit(false, {"error": "无法发送觉醒请求：%s" % error}, action_id, target_id)


func operate_campus_message(action_id: String, target_id: String, text: String = "") -> void:
	if target_id.is_empty():
		campus_phone_message_completed.emit(false, {"error": "未指定联系人"}, action_id, target_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_phone_message_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他操作"}, action_id, target_id)
		return
	_campus_busy = true
	_campus_pending_operation = "message"
	_campus_pending_message_target_id = target_id
	_campus_pending_message_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var parameters := {"target_id": target_id}
	if action_id == "SEND_PHONE_MESSAGE":
		parameters["text"] = text
	var command := {
		"command_id": "godot-message-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [target_id],
		"parameters": parameters,
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_message_target_id = ""
		_campus_pending_message_action = ""
		campus_phone_message_completed.emit(false, {"error": "无法发送手机消息：%s" % error}, action_id, target_id)


func operate_campus_dialogue(target_id: String, intent_id: String, text: String) -> void:
	if target_id.is_empty():
		campus_dialogue_completed.emit(false, {"error": "未指定交谈对象"}, target_id)
		return
	if text.strip_edges().is_empty():
		campus_dialogue_completed.emit(false, {"error": "交谈内容不能为空"}, target_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_dialogue_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他操作"}, target_id)
		return
	_campus_busy = true
	_campus_pending_operation = "dialogue"
	_campus_pending_dialogue_target_id = target_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-dialogue-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "TALK_TO_NPC",
		"target_ids": [target_id],
		"parameters": {"target_id": target_id, "intent_id": intent_id, "text": text.strip_edges()},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_dialogue_target_id = ""
		campus_dialogue_completed.emit(false, {"error": "无法发送交谈请求：%s" % error}, target_id)


func operate_campus_social_proposal(
	target_id: String,
	proposal_type: String,
	channel: String,
	note: String = ""
) -> void:
	if target_id.is_empty():
		campus_social_proposal_completed.emit(false, {"error": "未指定提议对象"}, target_id, proposal_type)
		return
	if proposal_type.is_empty():
		campus_social_proposal_completed.emit(false, {"error": "未指定提议类型"}, target_id, proposal_type)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_social_proposal_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他操作"}, target_id, proposal_type)
		return
	_campus_busy = true
	_campus_pending_operation = "social_proposal"
	_campus_pending_proposal_target_id = target_id
	_campus_pending_proposal_type = proposal_type
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-proposal-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "MAKE_SOCIAL_PROPOSAL",
		"target_ids": [target_id],
		"parameters": {
			"target_id": target_id,
			"proposal_type": proposal_type,
			"channel": channel,
			"note": note.strip_edges(),
		},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_proposal_target_id = ""
		_campus_pending_proposal_type = ""
		campus_social_proposal_completed.emit(false, {"error": "无法发送提议请求：%s" % error}, target_id, proposal_type)


func respond_campus_social_proposal(proposal_id: String, accepted: bool) -> void:
	if proposal_id.is_empty():
		campus_social_proposal_response_completed.emit(false, {"error": "未指定待处理请求"}, proposal_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_social_proposal_response_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他操作"}, proposal_id)
		return
	_campus_busy = true
	_campus_pending_operation = "social_proposal_response"
	_campus_pending_proposal_id = proposal_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-proposal-response-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": "RESPOND_SOCIAL_PROPOSAL",
		"target_ids": [],
		"parameters": {"proposal_id": proposal_id, "accepted": accepted},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_proposal_id = ""
		campus_social_proposal_response_completed.emit(false, {"error": "无法发送请求答复：%s" % error}, proposal_id)


func operate_campus_night_world(action_id: String) -> void:
	if action_id not in ["ENTER_NIGHT_WORLD", "EXIT_NIGHT_WORLD"]:
		campus_night_world_operation_completed.emit(false, {"error": "未知夜相操作"}, action_id)
		return
	if _campus_busy or not connected or campus_snapshot.is_empty():
		campus_night_world_operation_completed.emit(false, {"error": "校园模拟尚未连接或正在处理其他操作"}, action_id)
		return
	_campus_busy = true
	_campus_pending_operation = "night_world"
	_campus_pending_night_action = action_id
	_campus_command_counter += 1
	var clock: Dictionary = campus_snapshot.get("clock", {})
	var command := {
		"command_id": "godot-night-world-%d-%d" % [Time.get_ticks_usec(), _campus_command_counter],
		"actor_id": "player",
		"action_id": action_id,
		"target_ids": [],
		"parameters": {},
		"expected_world_revision": int(campus_snapshot.get("revision", 1)),
		"issued_day": int(clock.get("day", 1)),
		"issued_phase": String(clock.get("phase", "morning")),
		"issued_minute": int(clock.get("minute", 0)),
		"source": "player",
	}
	var error := _campus_request.request(
		_base_url + "/kernel/command", PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST, JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_night_action = ""
		campus_night_world_operation_completed.emit(false, {"error": "无法发送夜相请求：%s" % error}, action_id)


func request_npc_chronicle(
	npc_id: String,
	filter_name: String = "recent",
	cursor: String = "",
	limit: int = 20
) -> void:
	if npc_id.is_empty():
		campus_npc_chronicle_loaded.emit(false, {"error": "未指定人物"}, npc_id, filter_name)
		return
	if _chronicle_busy or not connected:
		campus_npc_chronicle_loaded.emit(false, {"error": "人物日志正在加载或服务尚未连接"}, npc_id, filter_name)
		return
	_chronicle_busy = true
	_chronicle_npc_id = npc_id
	_chronicle_filter = filter_name
	var url := "%s/kernel/npcs/%s/chronicle?filter=%s&limit=%d" % [
		_base_url, npc_id.uri_encode(), filter_name.uri_encode(), clampi(limit, 1, 50),
	]
	if not cursor.is_empty():
		url += "&cursor=" + cursor.uri_encode()
	var error := _chronicle_request.request(url)
	if error != OK:
		_chronicle_busy = false
		campus_npc_chronicle_loaded.emit(false, {"error": "无法发送人物日志请求：%s" % error}, npc_id, filter_name)


func phase_display_name(phase: String) -> String:
	return {"morning": "上午", "afternoon": "下午", "evening": "晚间", "late_night": "深夜"}.get(phase, phase)


func weekday_display_name(index: int) -> String:
	return ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][clampi(index, 0, 6)]


func _start_server() -> void:
	var script_path := ProjectSettings.globalize_path(SERVER_SCRIPT)
	var python_command := "python" if OS.has_feature("windows") else "python3"
	server_pid = OS.create_process(
		python_command,
		PackedStringArray([script_path, "--port", str(_server_port)]),
		false
	)
	if server_pid <= 0:
		connection_state_changed.emit(false, "无法启动 Python 模拟服务，请确认 %s 命令可用" % python_command)


func _request_snapshot() -> void:
	if busy or _request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_pending_operation = "snapshot"
	var error := _request.request(_base_url + "/snapshot")
	if error != OK:
		connected = false


func _on_request_completed(_result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var operation := _pending_operation
	_pending_operation = ""
	if response_code != 200:
		if operation == "configure":
			busy = false
			var error_payload = JSON.parse_string(body.get_string_from_utf8())
			interface_configured.emit(false, error_payload if error_payload is Dictionary else {"error": "HTTP %d" % response_code})
		elif operation == "step":
			_finish_with_error("模拟推进失败，HTTP %d" % response_code)
		elif operation == "trade":
			busy = false
			var trade_error = JSON.parse_string(body.get_string_from_utf8())
			trade_completed.emit(false, trade_error if trade_error is Dictionary else {"trade": {"message": "交易失败，HTTP %d" % response_code}})
		elif operation == "use_item":
			busy = false
			var use_error = JSON.parse_string(body.get_string_from_utf8())
			item_use_completed.emit(false, use_error if use_error is Dictionary else {"item_use": {"message": "使用失败，HTTP %d" % response_code}})
		elif operation == "action":
			busy = false
			var action_error = JSON.parse_string(body.get_string_from_utf8())
			if action_error is Dictionary:
				var failed_action_snapshot = action_error.get("snapshot", {})
				if failed_action_snapshot is Dictionary:
					snapshot = failed_action_snapshot
					snapshot_updated.emit(snapshot)
			action_completed.emit(false, action_error if action_error is Dictionary else {"action": {"message": "行动失败，HTTP %d" % response_code}})
		else:
			connected = false
			return
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		_finish_with_error("模拟服务返回了无效 JSON")
		return
	if operation == "configure":
		busy = false
		interface_configured.emit(true, parsed)
		return
	if operation == "trade":
		busy = false
		var trade_snapshot = parsed.get("snapshot", {})
		if trade_snapshot is Dictionary:
			snapshot = trade_snapshot
			snapshot_updated.emit(snapshot)
		trade_completed.emit(bool(parsed.get("ok", false)), parsed)
		return
	if operation == "use_item":
		busy = false
		var use_snapshot = parsed.get("snapshot", {})
		if use_snapshot is Dictionary:
			snapshot = use_snapshot
			snapshot_updated.emit(snapshot)
		item_use_completed.emit(bool(parsed.get("ok", false)), parsed)
		return
	if operation == "action":
		busy = false
		var action_snapshot = parsed.get("snapshot", {})
		if action_snapshot is Dictionary:
			snapshot = action_snapshot
			snapshot_updated.emit(snapshot)
		action_completed.emit(bool(parsed.get("ok", false)), parsed)
		return
	snapshot = parsed
	connected = true
	_retry_timer.stop()
	connection_state_changed.emit(true, "模拟服务已连接")
	snapshot_updated.emit(snapshot)
	if campus_snapshot.is_empty():
		refresh_campus_snapshot()
	if operation == "step":
		busy = false
		advance_state_changed.emit(false)


func _finish_with_error(message: String) -> void:
	busy = false
	connected = false
	advance_state_changed.emit(false)
	connection_state_changed.emit(false, message)
	_retry_timer.start()


func _on_campus_request_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var operation := _campus_pending_operation
	var passage_id := _campus_pending_passage_id
	var destination_id := _campus_pending_destination_id
	var task_id := _campus_pending_task_id
	var task_action := _campus_pending_task_action
	var club_id := _campus_pending_club_id
	var club_action := _campus_pending_club_action
	var party_target_id := _campus_pending_party_target_id
	var party_action := _campus_pending_party_action
	var combat_battle_id := _campus_pending_combat_battle_id
	var combat_action := _campus_pending_combat_action
	var cognition_target_id := _campus_pending_cognition_target_id
	var cognition_action := _campus_pending_cognition_action
	var message_target_id := _campus_pending_message_target_id
	var message_action := _campus_pending_message_action
	var dialogue_target_id := _campus_pending_dialogue_target_id
	var proposal_target_id := _campus_pending_proposal_target_id
	var proposal_type := _campus_pending_proposal_type
	var proposal_id := _campus_pending_proposal_id
	var night_action := _campus_pending_night_action
	_campus_pending_operation = ""
	_campus_pending_passage_id = ""
	_campus_pending_destination_id = ""
	_campus_pending_task_id = ""
	_campus_pending_task_action = ""
	_campus_pending_club_id = ""
	_campus_pending_club_action = ""
	_campus_pending_party_target_id = ""
	_campus_pending_party_action = ""
	_campus_pending_combat_battle_id = ""
	_campus_pending_combat_action = ""
	_campus_pending_cognition_target_id = ""
	_campus_pending_cognition_action = ""
	_campus_pending_message_target_id = ""
	_campus_pending_message_action = ""
	_campus_pending_dialogue_target_id = ""
	_campus_pending_proposal_target_id = ""
	_campus_pending_proposal_type = ""
	_campus_pending_proposal_id = ""
	_campus_pending_night_action = ""
	_campus_busy = false
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or not parsed is Dictionary:
		if operation == "inventory":
			campus_inventory_operation_completed.emit(false, parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"})
		elif operation == "traverse":
			var error_payload: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_traversal_completed.emit(false, error_payload, passage_id)
		elif operation == "advance_phase":
			var phase_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_phase_advanced.emit(false, phase_error)
		elif operation == "fast_travel":
			var travel_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_fast_travel_completed.emit(false, travel_error, destination_id)
		elif operation == "task":
			var task_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_task_operation_completed.emit(false, task_error, task_action, task_id)
		elif operation == "club":
			var club_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_club_operation_completed.emit(false, club_error, club_action, club_id)
		elif operation == "party":
			var party_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_party_operation_completed.emit(false, party_error, party_action, party_target_id)
		elif operation == "combat":
			var combat_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_combat_operation_completed.emit(false, combat_error, combat_action, combat_battle_id)
		elif operation == "cognition":
			var cognition_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_cognition_operation_completed.emit(false, cognition_error, cognition_action, cognition_target_id)
		elif operation == "message":
			var message_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_phone_message_completed.emit(false, message_error, message_action, message_target_id)
		elif operation == "dialogue":
			var dialogue_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_dialogue_completed.emit(false, dialogue_error, dialogue_target_id)
		elif operation == "social_proposal":
			var proposal_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_social_proposal_completed.emit(false, proposal_error, proposal_target_id, proposal_type)
		elif operation == "social_proposal_response":
			var response_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_social_proposal_response_completed.emit(false, response_error, proposal_id)
		elif operation == "night_world":
			var night_error: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_night_world_operation_completed.emit(false, night_error, night_action)
		return
	if operation == "snapshot":
		campus_snapshot = parsed
		campus_snapshot_updated.emit(campus_snapshot)
		return
	var updated_snapshot = parsed.get("snapshot", {})
	if updated_snapshot is Dictionary:
		campus_snapshot = updated_snapshot
		campus_snapshot_updated.emit(campus_snapshot)
	if operation == "inventory":
		campus_inventory_operation_completed.emit(bool(parsed.get("ok", false)), parsed)
	elif operation == "advance_phase":
		campus_phase_advanced.emit(bool(parsed.get("ok", false)), parsed)
	elif operation == "fast_travel":
		campus_fast_travel_completed.emit(bool(parsed.get("ok", false)), parsed, destination_id)
	elif operation == "task":
		campus_task_operation_completed.emit(bool(parsed.get("ok", false)), parsed, task_action, task_id)
	elif operation == "club":
		campus_club_operation_completed.emit(bool(parsed.get("ok", false)), parsed, club_action, club_id)
	elif operation == "party":
		campus_party_operation_completed.emit(bool(parsed.get("ok", false)), parsed, party_action, party_target_id)
	elif operation == "combat":
		campus_combat_operation_completed.emit(bool(parsed.get("ok", false)), parsed, combat_action, combat_battle_id)
	elif operation == "cognition":
		campus_cognition_operation_completed.emit(bool(parsed.get("ok", false)), parsed, cognition_action, cognition_target_id)
	elif operation == "message":
		campus_phone_message_completed.emit(bool(parsed.get("ok", false)), parsed, message_action, message_target_id)
	elif operation == "dialogue":
		campus_dialogue_completed.emit(bool(parsed.get("ok", false)), parsed, dialogue_target_id)
	elif operation == "social_proposal":
		campus_social_proposal_completed.emit(bool(parsed.get("ok", false)), parsed, proposal_target_id, proposal_type)
	elif operation == "social_proposal_response":
		campus_social_proposal_response_completed.emit(bool(parsed.get("ok", false)), parsed, proposal_id)
	elif operation == "night_world":
		campus_night_world_operation_completed.emit(bool(parsed.get("ok", false)), parsed, night_action)
	else:
		campus_traversal_completed.emit(bool(parsed.get("ok", false)), parsed, passage_id)


func _on_chronicle_request_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var npc_id := _chronicle_npc_id
	var filter_name := _chronicle_filter
	_chronicle_busy = false
	_chronicle_npc_id = ""
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or not parsed is Dictionary:
		var error_payload: Dictionary = parsed if parsed is Dictionary else {"error": "人物日志接口返回无效响应"}
		campus_npc_chronicle_loaded.emit(false, error_payload, npc_id, filter_name)
		return
	campus_npc_chronicle_loaded.emit(true, parsed, npc_id, filter_name)
