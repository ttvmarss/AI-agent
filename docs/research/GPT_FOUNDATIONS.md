# GPT Foundations — Research Memo (R-01, M0)

Status: research only. Nothing here is implemented. Written 2026-10-08.

## Source verification status

Each source was fetched in this session unless marked otherwise. "Secondary" means the primary page returned HTTP 403 to the fetch tool and the content was confirmed only through search-result summaries of a mirror, so wording must be re-checked against the original before it is quoted anywhere.

| # | Source | URL | Status |
|---|---|---|---|
| 1 | Vaswani et al., *Attention Is All You Need* | https://arxiv.org/abs/1706.03762 | **Verified** (arXiv page, v1 12 Jun 2017) |
| 2 | Radford et al., *Improving Language Understanding by Generative Pre-Training* (GPT-1) | https://cdn.openai.com/research-covers/language-unsupervised/language_understanding_paper.pdf | **Verified** (PDF text extracted; abstract read) |
| 3 | Radford et al., *Language Models are Unsupervised Multitask Learners* (GPT-2) | not fetched directly | **Unverified** — only the OpenAI release posts were targeted |
| 4 | OpenAI, GPT-2 1.5B release | https://openai.com/index/gpt-2-1-5b-release/ | **Secondary** (403 on openai.com; mirror via search summary says 5 Nov 2019, final stage of staged release) |
| 5 | OpenAI, *Introducing ChatGPT* | https://openai.com/index/chatgpt/ | **Secondary** (403; mirror via search summary: SFT on trainer-written dialogues, ranked comparisons for a reward model, PPO; "same methods as InstructGPT, different data collection") |
| 6 | Ouyang et al., *InstructGPT* | https://arxiv.org/abs/2203.02155 | **Verified** (arXiv page, 4 Mar 2022). The fetched abstract page itself does not name "reward model" or "PPO"; those terms come from the full paper/blog and need a full-text read |
| 7 | PyTorch install selector | https://pytorch.org/get-started/locally/ | Fetched, page dated 2026-07-27, but the selector is JavaScript-driven and no concrete version/CUDA matrix could be extracted. **Unverified** — owner's machine must be checked at M1 |

Not yet read at all (required reading list items): Microsoft UI Automation overview and administrator-privilege guidance (§1.2). Deferred to the M8/M9 research steps; flagged here so it is not forgotten.

## Chronology (history, as best verified)

1. **2017 — Transformer.** Attention-only sequence transduction, no recurrence/convolution. 28.4 BLEU WMT14 En-De; 41.8 BLEU En-Fr after 3.5 days on 8 GPUs. *Original was encoder-decoder for translation*, not a decoder-only language model.
2. **2018 — GPT-1.** Generative pre-training of a language model on unlabeled text, then discriminative fine-tuning per task with task-aware input transformations. Improves SOTA on 9 of 12 tasks studied (abstract). Architecture is a decoder-style Transformer (details to be copied from the paper's section 3 in the architecture ADR, not from memory).
3. **2019 — GPT-2.** Scaled autoregressive pre-training; staged release Feb → Nov 2019 (secondary source). Lesson for Zalius: a scale-up of the same recipe, with no task-specific pipelines.
4. **2022 — InstructGPT (Mar) and ChatGPT (30 Nov).** Three-step recipe: supervised fine-tuning on human demonstrations → reward model from human rankings → RL (PPO) against that reward. InstructGPT headline: 1.3B model preferred over 175B GPT-3 by labelers. ChatGPT blog describes the same approach with dialogue data (secondary source).

## What is history vs what Zalius will do

| Era / element | Historical | Zalius plan (modern implementation) |
|---|---|---|
| Architecture | Post-2017 attention blocks | Decoder-only, pre-norm, causal attention, tied embeddings; position scheme (learned vs RoPE) chosen by ADR after M3 smoke tests |
| Framework | TensorFlow/early PyTorch era | PyTorch; no assumption that historic libs are needed |
| Pretraining data | BooksCorpus (GPT-1), WebText (GPT-2) | Licence-reviewed corpora only; **no dataset chosen yet** |
| Scale | 117M to 1.5B params, large GPU/TPU fleets | E0 1–5M, E1 ~15–40M params on one 4 GB GPU, **unmeasured** |
| Alignment | Human labelers at scale, RM + PPO | SFT first on legally usable dialogues; RLHF/preference optimisation optional and later (blueprint §4.4 step 8) |
| Tokenizer | BPE (GPT-1/2 era) | BPE vs unigram decided at M2 on measured fertility/round-trip |

## Misconceptions to avoid

- Architectural resemblance does not give performance resemblance. InstructGPT's 1.3B result depended on a GPT-3 pretrained base with orders of magnitude more compute and data than Zalius can use.
- Neither the OpenAI posts nor the papers are a complete recipe for current ChatGPT. Zalius implements public principles only.
- Memory/retrieval in the app is not training (blueprint §3.2).

## Unknowns that remain open

1. Exact GPT-1/GPT-2 hyperparameters (read from papers in the M3 ADR, not recalled).
2. Re-verification of sources 4 and 5 against openai.com primary text (needs a browser session or a different fetch route).
3. Whether a clean, licence-clear corpus of sufficient size and quality exists for E1 (see `rights/SOURCE_RIGHTS_REGISTER.md`; candidates are listed there as *proposals*, none reviewed).
4. Achievable quality of a ~15–40M param model: expected to be a weak, mostly-fluent-fragment language model. **No claim of assistant-grade capability.**
