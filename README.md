# Amalgamma

Every four hours, Amalgamma reads a real headline from the BBC or NPR and reflects it as a fullscreen abstract composition. Not an illustration — a reflection. Like the headline's shadow on water.

## How it works

```
RSS feed (BBC/NPR) → LLM interprets mood & palette → algorithm generates CSS-art
```

1. **Source** — a real headline from `feeds.bbci.co.uk` or `feeds.npr.org`
2. **LLM** — free or paid backend interprets: mood, palette, structure, motion
3. **Grammar** — one of five visual grammars is selected based on the LLM's vision:
   - **atmospheric** — horizon, bands, particles, glass texture
   - **constructivist** — geometric blocks, SVG connection lines, paper-like background
   - **field** — dense point field, organic distribution, slow breathing
   - **pulse** — a single luminous form throbbing in darkness
   - **liquid** — overlapping translucent organic shapes bleeding into each other
4. **Artifact** — a self-contained HTML file: fullscreen, no scrollbars, hypnotic animation
5. **Cycle** — every 4 hours. The previous reflection disappears. Only the current one exists.

Temperature follows a 14-day sine wave with occasional random spikes — some reflections are coherent, others drift into glitch.

## The diptych

Amalgamma is one half of a pair:

- **Digital Garden** — creates text artifacts that live 4 hours and vanish. *Letting go.*
- **Amalgamma** — reflects the news cycle. *Witnessing.*

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

## Context

Created by [Natalia Martseniuk](https://github.com/look85-ops) — methodologist and L&D practitioner building artistic practice through autonomous AI systems. Amalgamma is a project about witnessing, not creating. About what a machine sees when it reads the news and cannot understand.