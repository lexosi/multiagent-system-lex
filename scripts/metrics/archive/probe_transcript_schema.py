#!/usr/bin/env python3
"""
probe_transcript_schema.py — Fase 5.1b probe.
Standalone, read-only. Validates CC v2.1.153 subagent JSONL schema.
Usage: python probe_transcript_schema.py <session_id>
Default session_id discovers from current CC project dir.

Output: JSON stdout with:
  - subagent_files: list of JSONL files found
  - schema_summary: per file, fields detected (agentId, attributionAgent, message.content count)
  - response_text_extractable: bool
  - mapping_1to1: bool (agentId -> attributionAgent unique mapping)
  - sample_phrases: top-5 substantive phrases from sample response
"""

import json
import os
import sys
from pathlib import Path
from collections import Counter

PROJECTS_DIR = Path(os.environ.get("USERPROFILE", os.environ.get("HOME"))) / ".claude" / "projects"
DEFAULT_PROJECT = "F--multiagent-system"

def discover_session_id(project_dir: Path) -> str | None:
    """Find most recent session in project dir."""
    candidates = sorted(
        project_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if candidates:
        return candidates[0].stem
    # Or look for session dir
    session_dirs = sorted(
        [d for d in project_dir.iterdir() if d.is_dir() and (d / "subagents").exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if session_dirs:
        return session_dirs[0].name
    return None

def analyze_subagent_file(path: Path) -> dict:
    """Read JSONL, count entries, extract key fields."""
    result = {
        "file": str(path),
        "lines": 0,
        "agentIds": set(),
        "attributionAgents": set(),
        "assistant_messages": 0,
        "text_content_blocks": 0,
        "response_excerpt": "",
    }
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                result["lines"] += 1
                try:
                    obj = json.loads(line)
                    if obj.get("agentId"):
                        result["agentIds"].add(obj["agentId"])
                    if obj.get("attributionAgent"):
                        result["attributionAgents"].add(obj["attributionAgent"])
                    msg = obj.get("message", {})
                    if msg.get("role") == "assistant" or obj.get("type") == "assistant":
                        result["assistant_messages"] += 1
                        for content_block in msg.get("content", []):
                            if isinstance(content_block, dict) and content_block.get("type") == "text":
                                result["text_content_blocks"] += 1
                                if not result["response_excerpt"]:
                                    result["response_excerpt"] = content_block.get("text", "")[:300]
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        result["error"] = str(e)
    # Convert sets to lists for JSON
    result["agentIds"] = sorted(result["agentIds"])
    result["attributionAgents"] = sorted(result["attributionAgents"])
    return result

def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    project_dir = PROJECTS_DIR / DEFAULT_PROJECT

    if not session_id:
        session_id = discover_session_id(project_dir)

    if not session_id:
        print(json.dumps({"error": "no session_id provided and discovery failed"}, indent=2))
        sys.exit(1)

    subagents_dir = project_dir / session_id / "subagents"

    result = {
        "session_id": session_id,
        "project_dir": str(project_dir),
        "subagents_dir": str(subagents_dir),
        "subagents_dir_exists": subagents_dir.exists(),
        "subagent_files": [],
        "schema_summary": [],
        "response_text_extractable": False,
        "mapping_1to1": True,
    }

    if subagents_dir.exists():
        files = sorted(subagents_dir.glob("agent-*.jsonl"))
        result["subagent_files"] = [f.name for f in files]

        agent_to_attribution = {}
        for f in files:
            analysis = analyze_subagent_file(f)
            result["schema_summary"].append(analysis)
            if analysis.get("text_content_blocks", 0) > 0:
                result["response_text_extractable"] = True
            for aid in analysis.get("agentIds", []):
                for att in analysis.get("attributionAgents", []):
                    if aid in agent_to_attribution and agent_to_attribution[aid] != att:
                        result["mapping_1to1"] = False
                    agent_to_attribution[aid] = att

    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
