# Amalgama

Every four hours, Amalgama reads a real headline from the BBC or NPR and responds to it as a fullscreen, non-figurative HTML/CSS composition. Not an illustration — a state. Like the headline's shadow on water.

## How it works

```
RSS feed (BBC/NPR) → artist prompt → LLM writes a code composition → browser renders it
```

1. **Source** — a real headline from `feeds.bbci.co.uk` or `feeds.npr.org`
2. **Artist prompt** — the LLM is asked to respond to the headline through rhythm, silence, scale, materiality and presence. It is told to keep its own voice, not imitate a named artist.
3. **LLM** — a free or paid backend writes one raw HTML `<div>` with inline CSS. No JSON, grammar catalogue, image model or fixed visual template.
4. **Artifact** — the code becomes a fullscreen browser composition. Empty space, lines, fields, marks and motion are chosen anew for the particular headline.
5. **Cycle** — every 4 hours. The previous reflection disappears. Only the current one exists.

The temperature is randomized within a warm range. Each cycle is an autonomous interpretation rather than a repeatable style preset.

## The diptych

Amalgama is one half of a pair:

- **[Digital Garden](https://github.com/look85-ops/digital-garden)** — creates text artifacts that live 4 hours and vanish. *Letting go.*
- **Amalgama** — reflects the news cycle. *Witnessing.*

One releases, the other receives. Together they ask: what happens to a signal when you stop holding on to it?

## Live

**Current reflection:** [look85-ops.github.io/amalgamma](https://look85-ops.github.io/amalgamma)

No memory. No archive. Only the current reflection exists.

## Technical

- Python 3.11+, requests, standard library
- Multi-backend LLM support: DeepSeek, OpenRouter, Gemini, Bothub proxy
- GitHub Actions cron every 4 hours
- Budget: $5/month. Free backends prioritized, paid as fallback.
- Archive stored at `artifacts/archive/` (not public)
- Each artifact includes a quiet procedural ambient layer: low drone, filtered noise and a sparse pulse. It is part of the browser experience, not a generated music track.

## Context

Created by [Natalia Martseniuk](https://github.com/look85-ops) — methodologist and L&D practitioner building artistic practice through autonomous AI systems. Amalgama is a project about witnessing, not illustrating. About what a machine sees when it reads the news and cannot understand.
