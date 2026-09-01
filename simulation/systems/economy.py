"""Current economy and essential-supply maintenance rules."""


def restock_essential_supplies(world):
    supplies = [
        ("object:market_food_crate", 70, 240, "市场摊贩与周边农场补充日常食物"),
        ("object:hospital_medicine", 8, 60, "医院药剂师完成药品调配与补给"),
        ("object:church_community_meal", 4, 80, "教会厨房补充救济餐"),
    ]
    for object_id, amount, capacity, reason in supplies:
        obj = world.objects[object_id]
        old = obj.quantity
        obj.quantity = min(capacity, obj.quantity + amount)
        if obj.quantity != old:
            world.ledger.emit(
                day=world.day,
                phase="night_resolution",
                system="supply_system",
                event_type="SUPPLY_RESTOCKED",
                message=f"{reason}：{obj.name} 从 {old} 补充到 {obj.quantity}。",
                scene_id=obj.scene_id,
                payload={
                    "object_id": object_id,
                    "old_quantity": old,
                    "new_quantity": obj.quantity,
                },
            )


__all__ = ["restock_essential_supplies"]
