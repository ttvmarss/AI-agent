import sys

from ..tokenizer.bpe import EOS

from ..tokenizer.template import IDENTITY_SYSTEM, TRAIL_ID, USER_ID, encode_turns
from .engine import Engine


def chat_loop(checkpoint, system="", temperature=0.7, top_k=40, top_p=0.9, max_tokens=200, seed=None, inp=sys.stdin, out=sys.stdout):
    eng = Engine.load(checkpoint)
    print(f"TRAIL runtime | checkpoint {eng.path} | weights sha256 {eng.fingerprint()[:16]} | {eng.model.num_parameters() / 1e6:.1f}M parameters | stage: {eng.stage}", file=out)
    if eng.stage == "pretrain":
        print("note: this is a BASE checkpoint. It continues text; it was not trained to answer. Run `trail instruct` to make TRAIL-V1-INSTRUCT.", file=out)
    print("(empty line or Ctrl-D to quit)", file=out)
    sysmsg = system or (IDENTITY_SYSTEM if eng.stage == "instruct" else "")
    history = []
    while True:
        out.write("\nYou   > "); out.flush()
        line = inp.readline()
        if not line or not line.strip():
            return 0
        history.append({"role": "user", "content": line.strip()})
        while True:                                           # drop the oldest turns until the prompt fits the context window
            ids = encode_turns(eng.tok, history, sysmsg)
            if len(ids) + max_tokens <= eng.cfg.max_seq_len or len(history) <= 1:
                break
            history = history[2:]
        out.write("TRAIL > "); out.flush()
        reply = []
        if eng.stage == "instruct":
            for piece in _stream_chat(eng, ids, temperature, top_k, top_p, max_tokens, seed):
                out.write(piece); out.flush(); reply.append(piece)
        else:                                                 # a base model has no chat protocol: continue the user's text
            for piece in eng.stream(line.strip(), max_new_tokens=max_tokens, temperature=temperature, top_k=top_k, top_p=top_p, seed=seed, repetition_penalty=1.1):
                out.write(piece); out.flush(); reply.append(piece)
        out.write("\n")
        history.append({"role": "assistant", "content": "".join(reply)})


def _stream_chat(eng, ids, temperature, top_k, top_p, max_tokens, seed):
    import codecs
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    for i in eng.stream_ids(ids, max_new_tokens=max_tokens, temperature=temperature, top_k=top_k, top_p=top_p, seed=seed, repetition_penalty=1.1,
                            stop_ids=(EOS, TRAIL_ID, USER_ID)):
        p = dec.decode(eng.tok.decode_bytes([i]))
        if p:
            yield p
    t = dec.decode(b"", final=True)
    if t:
        yield t
