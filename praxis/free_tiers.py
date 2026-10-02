"""Free cloud tiers, with PROVENANCE: where every number came from and when it was read (2026-10-02).

privacy classes (what the provider says it does with your prompts):
  cloud : documents no training and no/limited retention on API data   -> usable for 'project' goals
  open  : free-tier terms allow training, human review or logging     -> only for goals you mark 'open', and never with a secret in the prompt
Limits marked (community) come from a community-maintained list, not the vendor, and may be stale: a 429 is always honored.
"""
from dataclasses import dataclass

CHECKED = "2026-10-02"


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    base_url: str
    key_env: str
    models: tuple
    privacy: str
    rpm: int | None
    rpd: int | None
    tpd: int | None
    max_prompt_tokens: int | None
    caveat: str
    signup_url: str
    source: str
    checked: str = CHECKED
    kind: str = "openai"


PRESETS = [
    Preset("groq", "Groq (LPU inference)", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
           ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"), "cloud", 30, 1000, 200_000, 6000,
           "Only 8K tokens/minute on the free plan: PRAXIS keeps prompts small. Documented: no training on API data, no "
           "default retention (up to 30 days of abuse logs).",
           "https://console.groq.com/keys", "https://console.groq.com/docs/rate-limits"),
    Preset("cerebras", "Cerebras Inference", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY",
           ("gpt-oss-120b", "qwen-3.8-27b"), "cloud", 5, None, 1_000_000, 24000,
           "5 requests/minute, 1M tokens/day. Policy: prompts and outputs are not retained; it does not state a training policy.",
           "https://cloud.cerebras.ai", "https://inference-docs.cerebras.ai/support/rate-limits"),
    Preset("ollama-cloud", "Ollama Cloud", "https://ollama.com", "OLLAMA_API_KEY",
           ("gpt-oss:120b", "gemma4:31b"), "cloud", None, None, None, None,
           "Free plan = starter credits, 1 concurrent request; limits unpublished. Ollama: 'We do not use them to train models.'",
           "https://ollama.com/settings/keys", "https://docs.ollama.com/cloud", kind="ollama-cloud"),
    Preset("gemini", "Google Gemini API (free tier)", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
           ("gemini-3.8-flash",), "open", 15, None, None, None,
           "Free tier: Google uses prompts and responses to improve its products and humans may read them; 'do not submit "
           "sensitive, confidential, or personal information'. Limits vary by model (see AI Studio).",
           "https://aistudio.google.com/apikey", "https://ai.google.dev/gemini-api/terms"),
    Preset("mistral", "Mistral La Plateforme (Experiment tier)", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
           ("mistral-small-latest", "codestral-latest"), "open", 60, None, None, None,
           "About 1B tokens/month free, but free-tier conversations are training data by default unless you opt out.",
           "https://console.mistral.ai/api-keys", "https://docs.mistral.ai/"),
    Preset("nvidia", "NVIDIA NIM (trial)", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
           ("meta/llama-3.3-70b-instruct",), "open", 40, 10_000, None, None,
           "Trial use only: 'do not submit personal or confidential data'. Needs an NVIDIA Developer Program membership. (community)",
           "https://build.nvidia.com", "https://github.com/mnfst/awesome-free-llm-apis"),
    Preset("openrouter", "OpenRouter (:free models)", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
           (), "open", 20, 50, None, None,
           "20 requests/min and 50/day (1,000/day after buying $10 of credits); free providers may log prompts for training. "
           "The free list changes weekly: run `praxis free models openrouter`, then set `models = [...]`. (community)",
           "https://openrouter.ai/keys", "https://openrouter.ai/docs/api-reference/limits"),
]


@dataclass(frozen=True)
class Discontinued:
    name: str
    ended: str
    note: str
    source: str


DISCONTINUED = [
    Discontinued("Gemini CLI (free Google-login tier)", "2026-06-18",
                 "Google stopped serving free-account Gemini CLI requests; the new Antigravity CLI has a far smaller free quota.",
                 "https://geminicli.com/docs/resources/quota-and-pricing/"),
    Discontinued("Qwen Code (free OAuth tier)", "2026-04-15",
                 "The CLI is still free software, but the free hosted login ended; use your own API key.",
                 "https://github.com/QwenLM/qwen-code"),
    Discontinued("GitHub Models (free inference API)", "2026-07-30",
                 "Retired entirely: playground, catalog and inference API.",
                 "https://docs.github.com/en/github-models"),
]


def preset(pid):
    return next(p for p in PRESETS if p.id == pid)
