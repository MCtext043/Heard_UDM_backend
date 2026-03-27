"""Maps display/event types to RTDB-style review buckets (legacy client compatibility)."""


def review_bucket_for_type(type_value: str | None) -> str | None:
    if not type_value:
        return "Other"
    t = type_value.strip().lower()
    mapping = [
        (("кино", "cinema"), "Cinema"),
        (("театр", "theater", "theatre"), "Theater"),
        (("парк", "park"), "Park"),
        (("ресторан", "restaurant"), "Restaraunt"),
        (("музей", "museum"), "Museum"),
    ]
    for keys, bucket in mapping:
        if any(k in t for k in keys):
            return bucket
    return "Other"
