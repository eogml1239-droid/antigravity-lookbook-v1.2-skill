#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_transcript.py - Tier 0 (0-token) Antigravity transcript.jsonl -> JACC window.md extractor.

Zero external dependencies. Python 3.10+.
Extracts verbatim USER_INPUT and PLANNER_RESPONSE content from Antigravity transcript.jsonl,
stripping tool output noise (GENERIC) and internal thinking blocks to minimize tokens while
preserving 100% verbatim spans for JACC.

Usage:
  py -3 ingest_transcript.py --transcript <path/to/transcript.jsonl> --out <window.md> [--last-turns 40]
"""
from __future__ import annotations
import argparse
import json
import os
import sys


def est_tokens(text: str) -> int:
    """Matches jacc.py conservative estimator (len // 2)."""
    return max(1, len(text) // 2)


def ingest(transcript_path: str, out_path: str, last_turns: int = 0) -> dict:
    with open(transcript_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    raw_tokens = est_tokens(raw_text)
    entries: list[str] = []
    turn_count = 0
    step_count = 0

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        step_count += 1
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        stype = obj.get("type")
        content = (obj.get("content") or "").strip()
        if not content:
            continue

        if stype == "USER_INPUT":
            turn_count += 1
            entries.append(f"사용자: {content}")
        elif stype == "PLANNER_RESPONSE":
            entries.append(f"어시스턴트: {content}")

    if last_turns > 0 and len(entries) > last_turns * 2:
        entries = entries[-(last_turns * 2):]

    window_text = "\n\n".join(entries) + ("\n" if entries else "")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(window_text)

    win_tokens = est_tokens(window_text)
    reduction_pct = round((1.0 - (win_tokens / raw_tokens)) * 100.0, 2) if raw_tokens > 0 else 0.0

    return {
        "transcript": transcript_path,
        "out": out_path,
        "total_steps": step_count,
        "user_turns": turn_count,
        "extracted_messages": len(entries),
        "raw_tokens_est": raw_tokens,
        "window_tokens_est": win_tokens,
        "noise_reduction_pct": reduction_pct,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Antigravity transcript.jsonl -> JACC window.md ingestor")
    ap.add_argument("--transcript", required=True, help="Path to transcript.jsonl")
    ap.add_argument("--out", required=True, help="Output window.md path")
    ap.add_argument("--last-turns", type=int, default=0, help="Keep only last N turns (0 = all)")
    args = ap.parse_args()

    res = ingest(args.transcript, args.out, last_turns=args.last_turns)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
