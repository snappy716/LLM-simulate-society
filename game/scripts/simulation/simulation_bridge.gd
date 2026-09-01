extends Node

signal snapshot_updated(snapshot: Dictionary)
signal connection_state_changed(connected: bool, message: String)
signal advance_state_changed(busy: bool)
signal interface_configured(success: bool, result: Dictionary)

const BASE_URL := "http://127.0.0.1:8765"
const SERVER_SCRIPT := "res://tools/simulation/godot_simulation_server.py"

var snapshot: Dictionary = {}
var server_pid := -1
var connected := false
var busy := false
var _request: HTTPRequest
var _retry_timer: Timer
var _pending_operation := ""


func _ready() -> void:
	_request = HTTPRequest.new()
	_request.timeout = 180.0
	_request.request_completed.connect(_on_request_completed)
	add_child(_request)
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
		else:
			connected = false
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		_finish_with_error("模拟服务返回了无效 JSON")
		return
	if operation == "configure":
		busy = false
		interface_configured.emit(true, parsed)
		return
	snapshot = parsed
	connected = true
	_retry_timer.stop()
	connection_state_changed.emit(true, "模拟服务已连接")
	snapshot_updated.emit(snapshot)
	if operation == "step":
		busy = false
		advance_state_changed.emit(false)


func _finish_with_error(message: String) -> void:
	busy = false
	connected = false
	advance_state_changed.emit(false)
	connection_state_changed.emit(false, message)
	_retry_timer.start()
