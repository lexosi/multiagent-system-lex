"""Shared regex constants across deepseek_*.py wrappers (TD-024 R1 resolution).

Centralized to avoid drift between wrappers (formerly duplicated TASK_ID_RE 6x +
ATTEMPTS_LOG_RE 1x in hypothesis_tracker). Compiled module-level at import — fail-loud
early on broken pattern.

Patterns preserved verbatim from prior disco state (hypothesis_tracker.py L56, L64).
"""
import re

TASK_ID_RE = re.compile(r"^AR_[A-Za-z0-9_-]+$")
ATTEMPTS_LOG_RE = re.compile(r"^-\s*attempts:\s*(\d+)\s*$")
