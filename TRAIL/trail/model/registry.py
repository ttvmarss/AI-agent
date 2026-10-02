"""Component registry: how future generations replace a part without rewriting the model. config.components maps kind -> name."""
_REG = {}


def register(kind, name):
    def deco(obj):
        _REG.setdefault(kind, {})[name] = obj
        return obj
    return deco


def build(kind, name, *args, **kw):
    try:
        factory = _REG[kind][name]
    except KeyError:
        known = sorted(_REG.get(kind, {}))
        raise ValueError(f"no {kind} component named {name!r}; registered: {known}")
    return factory(*args, **kw)


def available():
    return {k: sorted(v) for k, v in _REG.items()}
