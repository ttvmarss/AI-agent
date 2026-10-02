"""Conversation format. Roles are single special tokens, so user text can never impersonate a role: user text is encoded WITHOUT special-token parsing."""
from .bpe import BOS, EOS, SPECIAL_TOKENS

SYSTEM_ID, USER_ID, TRAIL_ID = SPECIAL_TOKENS.index("<SYSTEM>"), SPECIAL_TOKENS.index("<USER>"), SPECIAL_TOKENS.index("<TRAIL>")
IDENTITY_SYSTEM = "You are TRAIL, a language model built by the TRAIL Project on the TRAIL Cognitive Engine (TCE-G1)."


def encode_turns(tok, messages, system="", add_generation_prompt=True):
    """messages: [{'role': 'user'|'assistant', 'content': str}, ...] -> token ids ending with <TRAIL> ready for the model to continue."""
    ids = [BOS]
    if system:
        ids += [SYSTEM_ID] + tok.encode(system)
    for m in messages:
        if m["role"] == "user":
            ids += [USER_ID] + tok.encode(m["content"])
        elif m["role"] == "assistant":
            ids += [TRAIL_ID] + tok.encode(m["content"]) + [EOS]
        else:
            raise ValueError(f"unknown role {m['role']!r}")
    if add_generation_prompt:
        ids.append(TRAIL_ID)
    return ids


def encode_training_example(tok, system, user, assistant):
    """-> (ids, loss_mask): only the assistant's words and its <EOS> are trained on."""
    prompt = encode_turns(tok, [{"role": "user", "content": user}], system, add_generation_prompt=True)
    answer = tok.encode(assistant) + [EOS]
    return prompt + answer, [0] * len(prompt) + [1] * len(answer)
