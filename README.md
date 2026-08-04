# multiagent-system

[![CI](https://github.com/lexosi/multiagent-system-lex/actions/workflows/ci.yml/badge.svg)](https://github.com/lexosi/multiagent-system-lex/actions/workflows/ci.yml)

> **Process discipline enforced by hooks, not good faith.**
> A root-driven multi-agent harness where enforcement is a first-class layer:
> advisory rules produced no measurable behavioral change across 171 documented runs; enforcement was
> redesigned as hard-block hooks that prevent violations by construction.

A root-driven multi-agent orchestration system built on Claude Code's native subagents, augmented with a small set of Python worker wrappers that call a secondary LLM provider directly. It coordinates debugging and feature work across multiple language/runtime domains (Verse/UEFN, Python, Rust, Java, TypeScript) through specialized agents, artifact-based handoff, and enforcement hooks. The production system runs 19 agents (13 Claude reasoners + 6 DeepSeek workers); this public snapshot contains 17 sanitized agent definitions.

The architecture is deliberately **root-driven**: a single main thread ("root") is the only physical invoker of subagents. Root produces an explicit plan, invokes one specialist per step, collects each report, and decides the next step — subagents never orchestrate each other. Work is handed off through on-disk artifacts (per-run plan, hypotheses, reports) rather than shared mutable state, and a layer of hooks enforces session discipline (path substitution at session start, protected-file guards, role/scope enforcement, and reactive end-of-turn checks).

## Engineering highlights

- **Role-discipline hard-block.** Specialized agents own their territory — planner owns plans, implementer owns templates, curator owns reports — and the orchestrator can't usurp them. Enforced per-action by a `PreToolUse` hook that discriminates the caller by `agent_type`; root authorizes a single edit via a one-shot, TTL-bounded override file, **not** a session-wide bypass. Built after an advisory-only version was measured to produce no behavioral change across 171 documented runs.
- **Anti-sycophancy, in layers.** "No changes needed" and "no blockers" are valid outputs. Agents are constrained not to invent work to look productive: implementer touches one file per turn, a one-line change stays one line, and collateral findings become tickets instead of silent scope creep.
- **Anti-loop hypothesis discipline.** Probe before fix — a hypothesis without a confirming probe is rejected. Bounded retry with mandatory escalation, plus source-of-truth divergence checks before chasing a logic bug. Human observation outranks the agent's own hypothesis when the two disagree.
- **Hybrid LLM routing.** Reasoning-heavy roles run on the high tier (Opus); high-volume grunt work is delegated to a secondary worker provider through thin `Task → Bash → Python` wrappers — a pragmatic split the runtime doesn't natively support.

## How it fits together

- **~16 registered agents** (source of truth: `config/agents.json`):
  - Planning / review / specialist / audit agents run on the high tier (Opus). Their prompts live in `agent_templates/*.md`.
  - Four **thin-wrapper** agents bridge `Task → Bash → Python` to call the secondary provider for grunt work (research, hypothesis tracking, doc writing, tech-debt scanning).
- **Skills** (`agent_templates/skills/**`) preload domain knowledge into specific agents via the `skills:` frontmatter field, scoped per domain (`*-uefn`, `*-unreal`, `*-blender`).
- **Hooks** (`hooks/*.ps1`):
  - `SessionStart` — regenerates `.claude/agents/` and `.claude/skills/` from templates, substituting `{{paths.*}}` placeholders (UTF-8 **without BOM**).
  - `PreToolUse` — protected-file guard, scope-territory hard-block (`agent_type`-aware, with a one-shot override), KB advisory, and Task-invocation capture.
  - `Stop` — reactive, non-blocking checks (curator pending, auditor pending, skills token-tax capture). Always exit 0.
- **Python wrappers** (`scripts/agents/*.py`) inherit from `_deepseek_wrapper_base.py`, emit a JSON envelope to stdout, and write a per-invocation audit file.

Generated runtime artifacts (`.claude/agents/`, `.claude/skills/`) are **not** committed — they are produced from `agent_templates/` on the first session start.

## Showcase, not runtime out-of-box

> This repository is a **showcase of the system's structure** (agents, skills, hooks, enforcement logic). It is **not** runnable as-is: absolute paths have been replaced with placeholders, and the runtime `config/paths.json` is intentionally excluded (use `config/paths.example.json` as the template). You must wire paths to your own machine before it will operate.

## Paths to configure

Replace these placeholders / paths with your own locations:

| Placeholder / path | Meaning | Where it appears |
|---|---|---|
| `<uefn_root>` | Parent folder of your UEFN projects | hooks, `config/paths-schema.md`, UEFN skills |
| `<projects_root>` | Parent folder of your Blender/asset projects | Blender skills |
| `<unreal_projects_root>` | Parent folder of your Unreal Editor projects | Unreal skills |
| `<repo_root>/...` | Absolute path to **this** repo (used in hook commands) | `.claude/settings.json` |
| `config/paths.json` | Runtime path config — **create your own** from `config/paths.example.json` | (gitignored) |

Folder-name tokens inside hook regexes (e.g. `UEFNProjects`) are generic examples — adjust them to match your real working directories. Per-machine overrides are supported via the `MULTIAGENT_PATHS_CONFIG` environment variable.

## Layout

```
agent_templates/   Agent prompts (source of truth) + skills/
config/            agents.json, models.json, kb_tiers.json, triggers.json, paths.example.json
hooks/             SessionStart / PreToolUse / Stop hooks (PowerShell)
scripts/agents/    Python worker wrappers (secondary-provider bridge)
scripts/metrics/   Token-tax instrumentation
docs/architecture/ Model-allocation notes
.claude/           settings.json (hook wiring)
CLAUDE.md          Project guidance loaded by Claude Code
```
