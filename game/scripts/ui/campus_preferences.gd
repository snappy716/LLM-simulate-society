extends Node
## Local presentation preferences, separate from API secrets and world saves.
var values := {"volume": 1.0, "muted": false, "font_size": 16, "reduced_motion": false, "fps": 60}
const PATH := "user://campus_presentation.cfg"

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var config := ConfigFile.new()
	if config.load(settings_path()) == OK:
		for key in values:
			var value: Variant = config.get_value("presentation", key, values[key])
			if typeof(value) == typeof(values[key]): values[key] = value
	apply()

func settings_path() -> String:
	var isolated := OS.get_environment("GODOT_SIM_SETTINGS_PATH")
	return PATH if isolated.is_empty() else isolated.get_base_dir().path_join("presentation.cfg")

func apply() -> void:
	values.volume = clampf(values.volume, 0, 1)
	values.font_size = clampi(values.font_size, 16, 18)
	if values.fps not in [30, 60, 120]: values.fps = 60
	AudioServer.set_bus_volume_linear(0, values.volume)
	AudioServer.set_bus_mute(0, values.muted)
	Engine.max_fps = values.fps
	var theme := load("res://ui/themes/campus_theme.tres") as Theme
	theme.default_font_size = values.font_size

func persist() -> Error:
	apply()
	var config := ConfigFile.new()
	for key in values: config.set_value("presentation", key, values[key])
	return config.save(settings_path())
