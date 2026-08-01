# Architecture Diagrams

| File | Content |
|---|---|
| `high-level.drawio` | The full system topology (dialer → carrier → media → CPU-tier services → GPU-tier services → compliance/human escalation). Open at [app.diagrams.net](https://app.diagrams.net) (File → Open From → Device). |
| `sequence-diagram.mmd` | One call turn, traced across every service boundary — the source behind the walkthrough in `docs/architecture.md`. |
| `deployment-diagram.mmd` | Per-region infra topology (CPU tier / GPU tier / coordinator tier / edge), matching `docs/scaling.md`'s capacity numbers. |
| `call-flow.mmd` | The `services/compliance` FSM as a state diagram — mirrors `libs/voice_agent_core/dialogue/fsm.py`'s `TRANSITIONS` table exactly. |
| `single-call-flow.html` | **Rendered, ready to open** — one borrower turn at engineering detail: every cache check (session state, intent, compliance FSM, TTS phrase), every timeout/retry, and the escalation branch that permanently exits the flow. No external dependencies — hand-drawn inline SVG, opens in any browser, matches both light/dark themes. |

## Why `.mmd`/`.drawio` sources instead of rendered `.png` files

These are diagram **sources** (Mermaid text and draw.io XML) rather than rendered raster images, since producing a real `sequence-diagram.png`/`deployment-diagram.png`/`call-flow.png` requires a diagram-rendering tool (`mmdc`, the Mermaid CLI, or draw.io itself) that isn't part of this environment. Rendering a `.mmd` source to PNG:

```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i sequence-diagram.mmd -o sequence-diagram.png
mmdc -i deployment-diagram.mmd -o deployment-diagram.png
mmdc -i call-flow.mmd -o call-flow.png
```

`docs/architecture.md` also embeds the high-level and audio-pipeline flowcharts directly as Mermaid code blocks, which render inline in any Markdown viewer that supports Mermaid (GitHub, most IDEs) without a separate render step.
