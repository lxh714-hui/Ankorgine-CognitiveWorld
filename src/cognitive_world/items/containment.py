"""Direct-parent spatial resolution; no canonical state or write authority."""


def effective_location(world, entity_id, *, maximum_depth=64):
    """Resolve existing direct location links, failing closed on ambiguity/cycles."""
    if type(maximum_depth) is not int or not 1 <= maximum_depth <= 64:
        raise ValueError("bounded spatial depth required")
    seen = set()
    current = entity_id
    for _ in range(maximum_depth):
        if current in seen:
            raise ValueError("cyclic location chain")
        seen.add(current)
        entity = world.get_entity(current)
        if entity is None:
            raise ValueError("missing spatial endpoint")
        if entity.type == "location":
            return current
        parent = world.get_location(current)
        if parent is None:
            raise ValueError("unknown effective location")
        current = parent
    raise ValueError("spatial depth budget exceeded")
