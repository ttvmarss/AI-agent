"""What the 'orbit' and the Fuel page show, computed from the real router, usage tracker and registry. No toolkit here."""
import time

from ..router import GOAL_RANK, PRIVACY_RANK, cost_class, family, provider_rank


def failover_chain(stack, data_class="project", role="planner"):
    """Model names in the order the router would try them for this goal right now."""
    return [p.card.name for p in stack.router.eligible(role, data_class)]


def provider_nodes(stack, data_class="project"):
    now = stack.router.clock()
    fams = {}
    for p in stack.providers:
        fams.setdefault(family(p.card.name), []).append(p)
    nodes = []
    for fam, members in fams.items():
        models = []
        for p in members:
            e = stack.registry.data.get(p.card.name, {}).get("planning", {})
            models.append({"name": p.card.name, "tier": getattr(p, "tier", None) or "", "score": e.get("score"),
                           "cost": e.get("cost_per_task"), "tps": e.get("tokens_per_s"),
                           "cooling_s": max(0, int(stack.router.cooling.get(p.card.name, 0) - now))})
        cooling = [m["cooling_s"] for m in models]
        first = members[0]
        nodes.append({
            "family": fam, "models": models, "privacy": first.card.privacy, "cost_class": cost_class(first),
            "pressure": max(stack.usage.pressure(p.card.name) for p in members),
            "cooling_s": min(cooling),     # the family rests only when EVERY model in it does: otherwise its earliest-free member is 0
            "blocked": provider_rank(first) > GOAL_RANK.get(data_class, 1),
            "delegate_only": not all(getattr(p, "can_complete", True) for p in members),
            "usage": stack.usage.summary(fam),
        })
    nodes.sort(key=lambda n: (n["cost_class"], PRIVACY_RANK.get(n["privacy"], 2), n["family"]))  # cheap, then trusted before open
    return nodes
