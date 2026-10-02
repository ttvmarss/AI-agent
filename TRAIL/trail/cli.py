"""`trail` command line: hardware | tokenizer train | data prepare | train | evaluate | chat | generate | instruct."""
import argparse
import json
import os
import sys

from .config import load_config, project_root, resolve
from .utilities.log import get_logger

log = get_logger("cli")


def _cfg(a):
    return load_config(resolve(a.config))


def cmd_hardware(a):
    from .hardware.detect import detect, report
    info = detect()
    print(json.dumps(info, indent=2) if a.json else report(info))
    return 0


def _paths(cfg):
    d = cfg.data
    out = resolve(d["output"])
    return {"out": out, "clean": os.path.join(out, "clean"), "shards": os.path.join(out, "shards"), "tok": os.path.join(out, "tokenizer")}


def _clean(cfg, p):
    from .data_foundry import pipeline
    d = cfg.data
    return pipeline.clean([resolve(s) for s in d["sources"]], p["clean"], base=project_root(), min_chars=d["min_chars"], max_chars=d["max_chars"],
                          allowed_categories=set(d["mixture"]), allow_unknown=d["allow_unknown_categories"])


def cmd_tokenizer(a):
    from .tokenizer import train as tt
    cfg = _cfg(a)
    p = _paths(cfg)
    if not os.path.isfile(os.path.join(p["clean"], "docs.jsonl")):
        _clean(cfg, p)
    t = cfg.tokenizer
    tok = tt.train_from_clean(p["clean"], p["tok"], t["vocab_size"], t["min_frequency"], t["sample_bytes"])
    texts = (json.loads(line)["text"] for line in open(os.path.join(p["clean"], "docs.jsonl"), encoding="utf-8"))
    n, bad, bpt = tt.roundtrip_check(tok, texts)
    print(f"tokenizer: vocab {tok.vocab_size}, round-trip {n - bad}/{n} exact, {bpt:.2f} bytes per token")
    return 0 if bad == 0 else 1


def cmd_data(a):
    from .data_foundry import pipeline
    from .tokenizer.bpe import Tokenizer
    cfg = _cfg(a)
    p = _paths(cfg)
    if a.action == "prepare":
        _clean(cfg, p)
        if not os.path.isfile(os.path.join(p["tok"], "tokenizer.json")):
            from .tokenizer import train as tt
            t = cfg.tokenizer
            tt.train_from_clean(p["clean"], p["tok"], t["vocab_size"], t["min_frequency"], t["sample_bytes"])
        tok = Tokenizer.load(p["tok"])
        m = pipeline.shard(p["clean"], tok, p["shards"], cfg.data["val_fraction"], cfg.digest())
        print(json.dumps({"totals": m["totals"], "categories": {c: {s: v["tokens"] for s, v in sp.items()} for c, sp in m["categories"].items()}}, indent=2))
        return 0
    if a.action == "report":
        r = json.load(open(os.path.join(p["clean"], "clean_report.json")))
        r.pop("sources", None)
        print(json.dumps(r, indent=2))
        return 0
    return 2


def cmd_train(a):
    from .training.trainer import Trainer
    cfg = load_config(resolve(a.config), overrides=json.loads(a.set) if a.set else None)
    return Trainer(cfg, resume=not a.fresh, max_steps=a.max_steps).run()


def cmd_evaluate(a):
    from .evaluation.suite import run_suite
    print(json.dumps(run_suite(a.checkpoint, resolve(a.config) if a.config else None), indent=2))
    return 0


def cmd_chat(a):
    from .inference.chat import chat_loop
    return chat_loop(a.checkpoint, system=a.system, temperature=a.temperature, top_k=a.top_k, top_p=a.top_p, max_tokens=a.max_tokens, seed=a.seed)


def cmd_generate(a):
    from .inference.engine import Engine
    eng = Engine.load(a.checkpoint)
    for piece in eng.stream(a.prompt, max_new_tokens=a.max_tokens, temperature=a.temperature, top_k=a.top_k, top_p=a.top_p, seed=a.seed,
                            repetition_penalty=a.repetition_penalty):
        sys.stdout.write(piece)
        sys.stdout.flush()
    print()
    return 0


def cmd_instruct(a):
    from .training.instruct import run_instruct
    return run_instruct(a.checkpoint, a.out, resolve(a.config))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trail", description="TRAIL: an original model lineage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cfg_default = "configs/trail_micro.yaml"

    def add(name, **kw):
        sp = sub.add_parser(name, **kw)
        return sp
    s = add("hardware"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_hardware)
    s = add("tokenizer"); s.add_argument("action", choices=["train"]); s.add_argument("--config", default=cfg_default); s.set_defaults(fn=cmd_tokenizer)
    s = add("data"); s.add_argument("action", choices=["prepare", "report"]); s.add_argument("--config", default=cfg_default); s.set_defaults(fn=cmd_data)
    s = add("train"); s.add_argument("--config", default=cfg_default); s.add_argument("--fresh", action="store_true", help="ignore an existing run directory's checkpoints")
    s.add_argument("--max-steps", type=int, default=0, help="stop early after this many total steps (the schedule still targets training.max_steps)")
    s.add_argument("--set", default="", help='JSON overrides, e.g. \'{"training": {"max_steps": 50}}\''); s.set_defaults(fn=cmd_train)
    s = add("evaluate"); s.add_argument("checkpoint"); s.add_argument("--config", default=""); s.set_defaults(fn=cmd_evaluate)
    for name, fn in (("chat", cmd_chat), ("generate", cmd_generate)):
        s = add(name); s.add_argument("checkpoint")
        if name == "generate":
            s.add_argument("prompt")
        s.add_argument("--temperature", type=float, default=0.8); s.add_argument("--top-k", type=int, default=50); s.add_argument("--top-p", type=float, default=0.95)
        s.add_argument("--max-tokens", type=int, default=200); s.add_argument("--seed", type=int, default=None)
        if name == "chat":
            s.add_argument("--system", default="")
        else:
            s.add_argument("--repetition-penalty", type=float, default=1.1)
        s.set_defaults(fn=fn)
    s = add("instruct"); s.add_argument("checkpoint", help="the BASE checkpoint directory"); s.add_argument("--out", required=True, help="new INSTRUCT run directory")
    s.add_argument("--config", default=cfg_default); s.set_defaults(fn=cmd_instruct)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
