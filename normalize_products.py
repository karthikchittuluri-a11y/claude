import re


# Sample data from three retail systems
pos_data = [
    {"product_code": "SKU001", "name": "Chef's Knife 8in", "price": 89.99},
    {"product_code": "SKU002", "name": "Cutting Board", "price": 34.99},
]

ecom_data = [
    {"sku": "sku-001", "product_name": "Chef's Knife 8 inch", "online_price": 89.99, "stock": 45},
    {"sku": "sku-003", "product_name": "Mixing Bowl Set", "online_price": 49.99, "stock": 12},
]

inventory_data = [
    {"item_id": "001", "description": "CHEFS KNIFE 8IN", "warehouse_qty": 120},
    {"item_id": "002", "description": "CUTTING BOARD", "warehouse_qty": 85},
]


def normalize_id(raw_id: str) -> str:
    """Extract the zero-padded numeric portion from any SKU format.

    Handles:
      'SKU001'  -> '001'
      'sku-001' -> '001'
      '001'     -> '001'
    """
    digits = re.sub(r"[^0-9]", "", raw_id)
    return digits.zfill(3)


def normalize_and_merge_products(pos, ecom, inventory):
    """Merge product records from POS, ecommerce, and inventory systems.

    Each system uses a different ID scheme; this function normalises them to a
    common zero-padded numeric key and returns one dict per unique product.

    Args:
        pos:       List of POS records       (keys: product_code, name, price)
        ecom:      List of ecommerce records (keys: sku, product_name, online_price, stock)
        inventory: List of inventory records (keys: item_id, description, warehouse_qty)

    Returns:
        List of merged product dicts sorted by normalized id.  Fields present
        only in a subset of systems are included as None when not available.
    """
    merged: dict[str, dict] = {}

    # --- POS ---
    for item in pos:
        nid = normalize_id(item["product_code"])
        merged.setdefault(nid, {"id": nid})
        merged[nid].update(
            {
                "product_code": item["product_code"],
                "name": item["name"],
                "price": item["price"],
            }
        )

    # --- Ecommerce ---
    for item in ecom:
        nid = normalize_id(item["sku"])
        merged.setdefault(nid, {"id": nid})
        merged[nid].update(
            {
                "online_price": item["online_price"],
                "stock": item["stock"],
            }
        )
        # Only set name from ecom if POS didn't already provide one
        merged[nid].setdefault("name", item["product_name"])

    # --- Inventory ---
    for item in inventory:
        nid = normalize_id(item["item_id"])
        merged.setdefault(nid, {"id": nid})
        merged[nid].update({"warehouse_qty": item["warehouse_qty"]})
        merged[nid].setdefault("name", item["description"].title())

    # Ensure every key exists in every record (None when missing)
    all_keys = ["id", "product_code", "name", "price", "online_price", "stock", "warehouse_qty"]
    result = []
    for nid, record in sorted(merged.items()):
        for key in all_keys:
            record.setdefault(key, None)
        result.append(record)

    return result


if __name__ == "__main__":
    products = normalize_and_merge_products(pos_data, ecom_data, inventory_data)
    for p in products:
        print(p)
