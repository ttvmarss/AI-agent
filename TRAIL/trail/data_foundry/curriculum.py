"""Curriculum engine: the mixture is a function of training progress, defined entirely in configuration (never in model code)."""


def normalize(mix):
    s = sum(mix.values())
    return {k: v / s for k, v in mix.items()} if s > 0 else dict(mix)


def mixture_at(step, total_steps, base_mixture, phases):
    """phases: [{until: fraction, mixture: {...}}, ...] in ascending `until`. No phases -> the static mixture."""
    if not phases:
        return normalize(base_mixture)
    frac = step / max(total_steps, 1)
    for ph in phases:
        if frac < ph["until"]:
            return normalize(ph["mixture"])
    return normalize(phases[-1]["mixture"])


def validate(phases):
    last = 0.0
    for ph in phases:
        if not 0 < ph["until"] <= 1 or ph["until"] <= last:
            raise ValueError("curriculum phases need strictly increasing `until` fractions in (0, 1]")
        last = ph["until"]
