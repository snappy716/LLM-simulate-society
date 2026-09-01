class_name AppearanceGenerator
extends RefCounted


static func generate(body_type: String, seed_value: int) -> Dictionary:
	var safe_body := body_type if body_type in ["male", "female"] else "male"
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value

	var result := {"body_type": safe_body}
	for slot in AppearanceCatalog.SLOTS:
		var ids := AppearanceCatalog.get_ids(safe_body, slot)
		if ids.is_empty():
			result[String(slot)] = "none"
		else:
			result[String(slot)] = ids[rng.randi_range(0, ids.size() - 1)]
	return result
