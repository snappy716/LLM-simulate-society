extends Node2D

@export var npc_scene: PackedScene
@export var npc_count := 8
@export var world_seed := 42


func _ready() -> void:
	call_deferred("_spawn_npcs")


func _spawn_npcs() -> void:
	if npc_scene == null:
		push_error("NPCSpawner 没有配置 npc_scene")
		return

	var anchors := get_tree().get_nodes_in_group("npc_spawn_anchor")
	if anchors.is_empty():
		push_error("测试场景没有 NPC 出生锚点")
		return

	for index in range(mini(npc_count, anchors.size())):
		var npc := npc_scene.instantiate()
		npc.npc_id = "npc_%03d" % (index + 1)
		npc.body_type = "male" if index % 2 == 0 else "female"
		npc.world_seed = world_seed
		add_child(npc)
		npc.global_position = (anchors[index] as Node2D).global_position
