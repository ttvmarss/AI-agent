import torch


def sample_next(logits, history, temperature=0.8, top_k=50, top_p=0.95, repetition_penalty=1.0, generator=None):
    """logits [V] -> next token id (int). temperature <= 0 is greedy (fully deterministic)."""
    logits = logits.float().clone()
    if repetition_penalty != 1.0 and history:
        idx = torch.unique(torch.as_tensor(history, dtype=torch.long))
        vals = logits[idx]
        logits[idx] = torch.where(vals > 0, vals / repetition_penalty, vals * repetition_penalty)
    if temperature <= 0:
        return int(logits.argmax())
    logits = logits / temperature
    if top_k and 0 < top_k < logits.numel():
        kth = torch.topk(logits, top_k).values[-1]
        logits[logits < kth] = float("-inf")
    probs = torch.softmax(logits, -1)
    if top_p and top_p < 1.0:
        sp, si = torch.sort(probs, descending=True)
        keep = torch.cumsum(sp, 0) - sp < top_p            # always keeps the most likely token
        sp = sp * keep
        probs = torch.zeros_like(probs).scatter(0, si, sp)
        probs = probs / probs.sum()
    return int(torch.multinomial(probs, 1, generator=generator))
