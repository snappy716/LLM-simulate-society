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

const BASE_URL := "http://127.0.0.1:8765"
const SERVER_SCRIPT := "res://tools/simulation/godot_simulation_server.py"

var snapshot: Dictionary = {}
var server_pid := -1
var connected := false
var busy := false
var _request: HTTPRequest
var _campus_request: HTTPRequest
var _retry_timer: Timer
var _pending_operation := ""
var campus_snapshot: Dictionary = {}
var _campus_busy := false
var _campus_pending_operation := ""
var _campus_pending_passage_id := ""
var _campus_command_counter := 0


func _ready() -> void:
	_request = HTTPRequest.new()
	_request.timeout = 180.0
	_request.request_completed.connect(_on_request_completed)
	add_child(_request)
	_campus_request = HTTPRequest.new()
	_campus_request.timeout = 30.0
	_campus_request.request_completed.connect(_on_campus_request_completed)
	add_child(_campus_request)
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
	var error := _request.request(BASE_URL + "/step", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, "{}")
	if error != OK:
		_finish_with_error("无法发送时间推进请求：%s" % error)


func configure_interface(config: Dictionary) -> void:
	if busy or not connected:
		interface_configured.emit(false, {"error": "模拟服务尚未连接或正在推进"})
		return
	busy = true
	_pending_operation = "configure"
	var body := JSON.stringify(config)
	var error := _request.request(BASE_URL + "/configure", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
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
	var error := _request.request(BASE_URL + "/trade", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
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
	var error := _request.request(BASE_URL + "/use-item", PackedStringArray(["Content-Type: application/json"]), HTTPClient.METHOD_POST, body)
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
		BASE_URL + "/action", PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST, JSON.stringify(payload))
	if error != OK:
		busy = false
		action_completed.emit(false, {"action": {"message": "无法发送行动请求：%s" % error}})


func refresh_campus_snapshot() -> void:
	if _campus_busy or not connected:
		return
	_campus_busy = true
	_campus_pending_operation = "snapshot"
	var error := _campus_request.request(BASE_URL + "/kernel/campus-snapshot")
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
		BASE_URL + "/kernel/command",
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(command)
	)
	if error != OK:
		_campus_busy = false
		_campus_pending_operation = ""
		_campus_pending_passage_id = ""
		campus_traversal_completed.emit(false, {"error": "无法发送校园移动请求：%s" % error}, passage_id)


func phase_display_name(phase: String) -> String:
	return {"morning": "上午", "afternoon": "下午", "evening": "晚间", "late_night": "深夜"}.get(phase, phase)


func weekday_display_name(index: int) -> String:
	return ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][clampi(index, 0, 6)]


func _start_server() -> void:
	var script_path := ProjectSettings.globalize_path(SERVER_SCRIPT)
	var python_command := "python" if OS.has_feature("windows") else "python3"
	server_pid = OS.create_process(python_command, PackedStringArray([script_path, "--port", "8765"]), false)
	if server_pid <= 0:
		connection_state_changed.emit(false, "无法启动 Python 模拟服务，请确认 %s 命令可用" % python_command)


func _request_snapshot() -> void:
	if busy or _request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_pending_operation = "snapshot"
	var error := _request.request(BASE_URL + "/snapshot")
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
	_campus_pending_operation = ""
	_campus_pending_passage_id = ""
	_campus_busy = false
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or not parsed is Dictionary:
		if operation == "traverse":
			var error_payload: Dictionary = parsed if parsed is Dictionary else {"error": "校园接口返回无效响应"}
			campus_traversal_completed.emit(false, error_payload, passage_id)
		return
	if operation == "snapshot":
		campus_snapshot = parsed
		campus_snapshot_updated.emit(campus_snapshot)
		return
	var updated_snapshot = parsed.get("snapshot", {})
	if updated_snapshot is Dictionary:
		campus_snapshot = updated_snapshot
		campus_snapshot_updated.emit(campus_snapshot)
	campus_traversal_completed.emit(bool(parsed.get("ok", false)), parsed, passage_id)
