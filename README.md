# Amalgama

Every four hours, Amalgama reads a real headline from the BBC or NPR and responds to it as a fullscreen, non-figurative HTML/CSS composition. Not an illustration — a state. Like the headline's shadow on water.

## How it works

```
RSS feed (BBC/NPR) → reflection → LLM writes a code composition → browser renders it
```

1. **Source** — a real headline from `feeds.bbci.co.uk` or `feeds.npr.org`, chosen at random. The machine does not decide what matters — it takes what falls out of the stream. That is the point: a witness without choice.
2. **Reflection** — the LLM first writes a short text: the weight, rhythm, state and silence of the headline. Not an illustration, not a summary — a feeling.
3. **Composition** — from that reflection, the LLM writes one raw HTML `<div>` with inline CSS. No JSON, no image model, no fixed visual template. Code is the paint.
4. **Artifact** — the code becomes a fullscreen browser composition. Empty space, lines, fields, marks and motion are chosen anew for the particular headline.
5. **Cycle** — every 4 hours. The previous reflection disappears. Only the current one exists.

The temperature is randomized within a warm range. Each cycle is an autonomous interpretation rather than a repeatable style preset.

## Live

**Current reflection:** [look85-ops.github.io/amalgamma](https://look85-ops.github.io/amalgamma)

No memory. No archive. Only the current reflection exists.

## Technical

- Python 3.11+, requests, standard library
- Multi-backend LLM support: DeepSeek, OpenRouter, Gemini, Bothub proxy
- Two-phase prompt: reflection (text) → composition (code)
- GitHub Actions cron every 4 hours
- Budget: $10/month. Free backends prioritized, paid as fallback.
- Archive stored at `artifacts/archive/` (not public)
- Each artifact includes a quiet procedural ambient layer: low drone, filtered noise and a sparse pulse. It is part of the browser experience, not a generated music track.

## Context

Created by Natalia Martseniuk — methodologist and L&D practitioner building artistic practice through autonomous AI systems. Amalgama is a project about witnessing, not illustrating. About what a machine sees when it reads the news and cannot understand.
