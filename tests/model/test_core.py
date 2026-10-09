import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "model" / "core"))
import torch
from zalius_core import CharTokenizer, CoreConfig, ZaliusCore


def tiny():
    torch.manual_seed(0)
    return ZaliusCore(CoreConfig(vocab_size=30, n_layer=2, n_head=2, d_model=32, ctx=16, dropout=0.0))


def test_tokenizer_roundtrip_and_unicode():
    t = CharTokenizer("héllo wörld — 日本\n")
    s = "héllo\n日本"
    assert t.decode(t.encode(s)) == s
    assert CharTokenizer.from_json(t.to_json()).itos == t.itos
    assert t.encode("☃") == [0]  # documented information loss: unknown -> <unk>


def test_causal_no_future_leakage():
    m = tiny().eval()
    a = torch.randint(1, 30, (1, 12))
    b = a.clone(); b[0, 8:] = (b[0, 8:] + 1) % 30
    la, _ = m(a); lb, _ = m(b)
    assert torch.allclose(la[0, :8], lb[0, :8], atol=1e-5)
    assert not torch.allclose(la[0, 8:], lb[0, 8:], atol=1e-5)


def test_initial_loss_near_uniform_and_finite():
    m = tiny(); x = torch.randint(1, 30, (4, 16))
    _, loss = m(x, x)
    assert torch.isfinite(loss) and abs(loss.item() - torch.log(torch.tensor(30.0)).item()) < 0.3


def test_gradients_flow_and_tiny_overfit():
    m = tiny(); x = torch.randint(1, 30, (2, 16))
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
    first = None
    for _ in range(150):
        _, loss = m(x[:, :-1], x[:, 1:]); opt.zero_grad(); loss.backward()
        assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in m.parameters())
        opt.step(); first = first or loss.item()
    assert loss.item() < 0.2 * first


def test_deterministic_generation():
    m = tiny().eval(); p = torch.tensor([[1, 2, 3]])
    assert torch.equal(m.generate(p, 8, seed=7), m.generate(p, 8, seed=7))
