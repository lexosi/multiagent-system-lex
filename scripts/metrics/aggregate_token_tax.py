#!/usr/bin/env python3
"""Aggregate skills token tax from JSONL captures (offline stdlib).

Reads .metrics/skills_token_tax.jsonl produced by hooks/stop-capture-skills-token-tax.ps1
and emits a markdown summary to stdout.

Approximation: chars/4 LOC-based, NOT exact tokenizer count (MVP).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_PATHS_JSON = Path("F:/multiagent-system/config/paths.json")
FALLBACK_JSONL = Path("F:/multiagent-system/.metrics/skills_token_tax.jsonl")


def resolve_default_jsonl() -> Path:
    """Resolve default JSONL path via config/paths.json state_files.metrics_dir."""
    try:
        with DEFAULT_PATHS_JSON.open("r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        metrics_dir = cfg.get("state_files", {}).get("metrics_dir")
        if metrics_dir:
            return Path(metrics_dir) / "skills_token_tax.jsonl"
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] paths.json resolve failed ({exc}); using fallback", file=sys.stderr)
    return FALLBACK_JSONL


def read_jsonl(path: Path) -> list[dict]:
    """Read JSONL line-by-line; skip blanks; log malformed lines to stderr."""
    entries: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[warn] line {lineno} malformed JSON, skipped ({exc})", file=sys.stderr)
    return entries


def _bin_label(n: int) -> str:
    """Histogram bin label for subagents-per-turn count."""
    if n == 0:
        return "0 subagents"
    if n == 1:
        return "1 subagent"
    if n <= 3:
        return "2-3 subagents"
    if n <= 5:
        return "4-5 subagents"
    return "6+ subagents"


def aggregate_dynamic_delta(entries: list[dict]) -> list[str]:
    """Build Fase 5.1 Dynamic vs Static delta markdown section.

    Returns list of markdown lines. Graceful fallback if no entries contain
    Fase 5.1 dynamic fields (actual_approx_tokens + subagents_invoked_this_turn).
    """
    lines: list[str] = ["## Dynamic vs Static delta (Fase 5.1)", ""]

    dynamic_entries: list[dict] = []
    for entry in entries:
        actual = entry.get("actual_approx_tokens")
        invoked = entry.get("subagents_invoked_this_turn") or []
        if actual is not None and len(invoked) > 0:
            dynamic_entries.append(entry)

    total_turns = len(entries)

    if not dynamic_entries:
        lines.append("_No turns contain Fase 5.1 dynamic fields yet. Static upper-bound only._")
        lines.append("")
        return lines

    statics = [int(e.get("total_approx_tokens", 0)) for e in dynamic_entries]
    actuals = [int(e.get("actual_approx_tokens", 0)) for e in dynamic_entries]
    static_avg = statistics.mean(statics) if statics else 0.0
    actual_avg = statistics.mean(actuals) if actuals else 0.0
    delta_pct = ((static_avg - actual_avg) / static_avg * 100) if static_avg > 0 else 0.0

    lines.append("_Note: actual = subset matching Task invocations capture; chars/4 heurística aún applies._")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Avg static upper-bound per turn | {static_avg:.1f} |")
    lines.append(f"| Avg actual (dynamic) per turn | {actual_avg:.1f} |")
    lines.append(f"| Delta % savings | {delta_pct:.1f}% |")
    lines.append(f"| Turns with dynamic data | {len(dynamic_entries)} / {total_turns} |")
    lines.append("")

    # Top-3 most-invoked subagents
    invocation_counter: Counter[str] = Counter()
    per_agent_turn_count: dict[str, int] = defaultdict(int)
    for entry in dynamic_entries:
        invoked = entry.get("subagents_invoked_this_turn") or []
        for name in invoked:
            invocation_counter[name] += 1
        seen: set[str] = set(invoked)
        for name in seen:
            per_agent_turn_count[name] += 1

    top3 = invocation_counter.most_common(3)
    lines.append("### Top-3 most-invoked subagents")
    lines.append("")
    lines.append("| Subagent | Invocations | Avg per turn |")
    lines.append("|---|---|---|")
    if top3:
        for name, count in top3:
            turn_count = per_agent_turn_count[name] or 1
            avg_per_turn = count / turn_count
            lines.append(f"| {name} | {count} | {avg_per_turn:.2f} |")
    else:
        lines.append("| _none_ | 0 | 0.00 |")
    lines.append("")

    # Histogram: subagents per turn distribution
    bin_counter: Counter[str] = Counter()
    bin_order = ["0 subagents", "1 subagent", "2-3 subagents", "4-5 subagents", "6+ subagents"]
    for entry in dynamic_entries:
        invoked = entry.get("subagents_invoked_this_turn") or []
        bin_counter[_bin_label(len(invoked))] += 1

    lines.append("### Subagents per turn distribution")
    lines.append("")
    lines.append("| Bin | Turns count |")
    lines.append("|---|---|")
    for label in bin_order:
        lines.append(f"| {label} | {bin_counter.get(label, 0)} |")
    lines.append("")

    return lines


def aggregate_false_positive_usage(entries: list[dict]) -> list[str]:
    """Compute false-positive skill usage from per_skill_usage field (Fase 5.1b).

    Approach: D1 substring + D4 curated phrases. False-positive = skill loaded
    BUT NOT cited verbatim. Graceful fallback if no entries contain per_skill_usage.
    """
    lines: list[str] = ["## False-positive skill usage (Fase 5.1b)", ""]

    fp_entries = [e for e in entries if e.get("per_skill_usage")]
    if not fp_entries:
        lines.append("_No turns contain Fase 5.1b per_skill_usage data yet._")
        lines.append("")
        return lines

    lines.append("_Approach: D1 substring + D4 curated phrases. False-positive = skill loaded BUT NOT cited verbatim._")
    lines.append("")

    skill_activations: dict[str, int] = defaultdict(int)
    skill_cites: dict[str, int] = defaultdict(int)

    for entry in fp_entries:
        per_skill = entry.get("per_skill_usage", [])
        for item in per_skill:
            skill = item.get("skill", "")
            status = item.get("status", "")
            if not skill:
                continue
            skill_activations[skill] += 1
            if status == "cited":
                skill_cites[skill] += 1

    if not skill_activations:
        lines.append("_No cited skills in current data._")
        lines.append("")
        return lines

    skill_stats: list[tuple[str, int, int, float]] = []
    for skill in sorted(skill_activations.keys()):
        acts = skill_activations[skill]
        cites = skill_cites.get(skill, 0)
        fp_ratio = 1 - (cites / acts) if acts > 0 else 0.0
        skill_stats.append((skill, acts, cites, fp_ratio))

    total_activations = sum(s[1] for s in skill_stats)
    total_cites = sum(s[2] for s in skill_stats)
    global_fp = 1 - (total_cites / total_activations) if total_activations > 0 else 0.0

    lines.append("### Global stats")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total activations | {total_activations} |")
    lines.append(f"| Total cites | {total_cites} |")
    lines.append(f"| Global false-positive ratio | {global_fp:.1%} |")
    lines.append(f"| Turns with Fase 5.1b data | {len(fp_entries)} / {len(entries)} |")
    lines.append("")

    skill_stats.sort(key=lambda x: -x[3])
    top5 = skill_stats[:5]
    lines.append("### Top-5 skills by false-positive rate (waste indicators)")
    lines.append("")
    lines.append("| Skill | Activations | Cites | FP Ratio |")
    lines.append("|---|---|---|---|")
    for skill, acts, cites, fp_ratio in top5:
        lines.append(f"| {skill} | {acts} | {cites} | {fp_ratio:.1%} |")
    lines.append("")

    return lines


def aggregate(entries: list[dict], top_n: int) -> str:
    """Return markdown report string."""
    if not entries:
        return "# Skills Token Tax — Aggregation Report\n\n_No entries found. Run a session to populate metrics._\n"

    totals = [int(e.get("total_approx_tokens", 0)) for e in entries]
    sum_total = sum(totals)
    avg_total = statistics.mean(totals) if totals else 0
    max_total = max(totals) if totals else 0
    min_total = min(totals) if totals else 0

    # Per-agent rollup: track max chars, max approx_tokens, list of skills_count
    per_agent_max_chars: dict[str, int] = defaultdict(int)
    per_agent_max_tokens: dict[str, int] = defaultdict(int)
    per_agent_skills_counts: dict[str, list[int]] = defaultdict(list)

    for entry in entries:
        for row in entry.get("per_agent", []):
            name = row.get("agent", "<unknown>")
            chars = int(row.get("skills_chars_sum", 0))
            tokens = int(row.get("approx_tokens", 0))
            count = int(row.get("skills_count", 0))
            if chars > per_agent_max_chars[name]:
                per_agent_max_chars[name] = chars
            if tokens > per_agent_max_tokens[name]:
                per_agent_max_tokens[name] = tokens
            per_agent_skills_counts[name].append(count)

    # Top-N by max chars
    ranked = sorted(per_agent_max_chars.items(), key=lambda kv: kv[1], reverse=True)[:top_n]

    lines: list[str] = []
    lines.append("# Skills Token Tax — Aggregation Report")
    lines.append("")
    lines.append(f"**Source**: `{entries[0].get('_source_path', '(jsonl)')}` (path passed via CLI)")
    lines.append(f"**Entries**: {len(entries)} turns")
    lines.append("")
    lines.append("_Approximation: chars/4 LOC-based, NOT exact tokenizer count (MVP)._")
    lines.append("")
    lines.append("## Global stats")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total approx tokens | {sum_total} |")
    lines.append(f"| Avg per turn | {avg_total:.1f} |")
    lines.append(f"| Max per turn | {max_total} |")
    lines.append(f"| Min per turn | {min_total} |")
    lines.append("")
    lines.extend(aggregate_dynamic_delta(entries))
    lines.extend(aggregate_false_positive_usage(entries))
    lines.append(f"## Top-{top_n} agents (by max skills_chars_sum)")
    lines.append("")
    lines.append("| Agent | Max chars | Max approx_tokens | Avg skills_count |")
    lines.append("|---|---|---|---|")
    for name, max_chars in ranked:
        counts = per_agent_skills_counts[name]
        avg_count = statistics.mean(counts) if counts else 0.0
        max_tokens = per_agent_max_tokens[name]
        lines.append(f"| {name} | {max_chars} | {max_tokens} | {avg_count:.1f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate skills token tax JSONL captures.")
    parser.add_argument("--jsonl", type=Path, default=None, help="Path to JSONL file (default: resolved via config/paths.json).")
    parser.add_argument("--top", type=int, default=5, help="Top-N agents by max skills_chars_sum (default 5).")
    args = parser.parse_args()

    # Force UTF-8 stdout (consistency with wrappers)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    jsonl_path = args.jsonl if args.jsonl is not None else resolve_default_jsonl()

    if not jsonl_path.exists():
        print(f"# Skills Token Tax — Aggregation Report\n\n_JSONL not found: `{jsonl_path}`. Run a session first._\n")
        return 0

    entries = read_jsonl(jsonl_path)
    # Inject source path into first entry meta for header rendering
    if entries:
        entries[0]["_source_path"] = str(jsonl_path)
    report = aggregate(entries, top_n=args.top)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
