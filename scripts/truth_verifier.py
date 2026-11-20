#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""truth_verifier.py - Tier 0 (0-token) Deterministic Verifier & Gate 1 Anti-Hallucination Scanner.

Zero external dependencies. Python 3.10+.
Mechanically checks:
  1. File existence, non-zero size, and SHA-256 checksums (--check-files)
  2. JACC Verbatim 100% integrity: every text span in jacc-record.json must be an exact substring of source (--check-verbatim)
  3. Report claim-vs-evidence scan: flags unsubstantiated "완료/문제없음/절감" claims lacking numeric/path/exit evidence (--check-report)

Usage:
  py -3 truth_verifier.py --selftest
  py -3 truth_verifier.py --check-files path1,path2
  py -3 truth_verifier.py --check-verbatim --source window.md --record records/selftest.json
  py -3 truth_verifier.py --check-report report.md
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

RE_STRONG_CLAIM = re.compile(
    r'(문제\s*없음|완벽히|100%\s*완료|정상\s*동작|이상\s*없음|대폭\s*절감|크게\s*향상|모두\s*통과)',
    re.I,
)
RE_EVIDENCE = re.compile(
    r'(\d+(?:\.\d+)?\s*(?:%|px|cm|ms|초|바이트|bytes|토큰|tokens|개)|exit\s*code\s*\d+|sha256|PASS|FAIL|SELFTEST|[A-Za-z]:\\|\.[a-z0-9]{2,5}\b)',
    re.I,
)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_files(paths: list[str]) -> dict:
    items = []
    all_ok = True
    for p in paths:
        exists = os.path.isfile(p)
        size = os.path.getsize(p) if exists else 0
        digest = sha256_file(p) if exists else None
        ok = exists and size > 0
        if not ok:
            all_ok = False
        items.append({
            "path": p,
            "exists": exists,
            "bytes": size,
            "sha256": digest,
            "pass": ok,
        })
    return {"check": "files", "pass": all_ok, "count": len(items), "items": items}


def _collect_record_texts(obj, trail="") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{trail}.{k}" if trail else k
            if k == "text" and isinstance(v, str):
                found.append((sub, v))
            else:
                found.extend(_collect_record_texts(v, sub))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.extend(_collect_record_texts(item, f"{trail}[{idx}]"))
    return found


def check_verbatim(source_path: str, record_path: str) -> dict:
    with open(source_path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(record_path, "r", encoding="utf-8") as f:
        rec = json.load(f)

    spans = _collect_record_texts(rec)
    violations = []
    matched = 0
    for loc, txt in spans:
        if txt in src:
            matched += 1
        else:
            violations.append({"location": loc, "text": txt})

    total = len(spans)
    rate = 100.0 if total == 0 else round((matched / total) * 100.0, 2)
    return {
        "check": "verbatim",
        "pass": len(violations) == 0,
        "total_spans": total,
        "matched_spans": matched,
        "match_rate_pct": rate,
        "violations": violations,
    }


def check_report(report_path: str) -> dict:
    with open(report_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    flags = []
    for idx, line in enumerate(lines, start=1):
        if RE_STRONG_CLAIM.search(line) and not RE_EVIDENCE.search(line):
            flags.append({"line": idx, "text": line.strip(), "reason": "근거 수치·경로·실측 출력 없는 단정 표현"})
    return {
        "check": "report_claims",
        "pass": len(flags) == 0,
        "flagged_count": len(flags),
        "flags": flags,
    }


def selftest() -> int:
    # 1. File check on itself
    r_files = check_files([os.path.abspath(__file__)])
    assert r_files["pass"] is True

    # 2. Verbatim check: PASS case & tampered FAIL case
    with tempfile.TemporaryDirectory() as td:
        src_p = os.path.join(td, "src.md")
        rec_ok = os.path.join(td, "ok.json")
        rec_bad = os.path.join(td, "bad.json")
        rep_bad = os.path.join(td, "rep_bad.md")
        rep_ok = os.path.join(td, "rep_ok.md")

        with open(src_p, "w", encoding="utf-8") as f:
            f.write("사용자: src/auth.py 수정 완료했습니다.\n")
        with open(rec_ok, "w", encoding="utf-8") as f:
            json.dump({"intent": [{"text": "사용자: src/auth.py 수정 완료했습니다."}]}, f, ensure_ascii=False)
        with open(rec_bad, "w", encoding="utf-8") as f:
            json.dump({"intent": [{"text": "이 문장은 원문에 없는 지어낸 요약입니다."}]}, f, ensure_ascii=False)
        with open(rep_bad, "w", encoding="utf-8") as f:
            f.write("모든 작업이 완벽히 정상 동작하며 문제없음.\n")
        with open(rep_ok, "w", encoding="utf-8") as f:
            f.write("selftest.py 실행 결과 exit code 0, Verbatim 100% 정상 동작 확인.\n")

        v_ok = check_verbatim(src_p, rec_ok)
        v_bad = check_verbatim(src_p, rec_bad)
        c_bad = check_report(rep_bad)
        c_ok = check_report(rep_ok)

        assert v_ok["pass"] is True and v_ok["match_rate_pct"] == 100.0
        assert v_bad["pass"] is False and len(v_bad["violations"]) == 1
        assert c_bad["pass"] is False and c_bad["flagged_count"] == 1
        assert c_ok["pass"] is True and c_ok["flagged_count"] == 0

    print(json.dumps({
        "selftest": "PASS",
        "file_check": {"pass": r_files["pass"], "bytes": r_files["items"][0]["bytes"]},
        "verbatim_ok_rate": v_ok["match_rate_pct"],
        "verbatim_tamper_caught": not v_bad["pass"],
        "unsubstantiated_claim_caught": not c_bad["pass"],
        "evidenced_claim_passed": c_ok["pass"],
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Antigravity Gate 1 Deterministic Verifier (Tier 0)")
    ap.add_argument("--selftest", action="store_true", help="Run built-in verification self-test")
    ap.add_argument("--check-files", type=str, default="", help="Comma-separated file paths to verify")
    ap.add_argument("--check-verbatim", action="store_true", help="Verify JACC record verbatim integrity")
    ap.add_argument("--source", type=str, default="", help="Source markdown file path")
    ap.add_argument("--record", type=str, default="", help="JACC record json file path")
    ap.add_argument("--check-report", type=str, default="", help="Report markdown file to scan for unsubstantiated claims")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    results = []
    overall_pass = True

    if args.check_files:
        paths = [p.strip() for p in args.check_files.split(",") if p.strip()]
        r = check_files(paths)
        results.append(r)
        overall_pass = overall_pass and r["pass"]

    if args.check_verbatim:
        if not args.source or not args.record:
            ap.error("--check-verbatim requires --source and --record")
        r = check_verbatim(args.source, args.record)
        results.append(r)
        overall_pass = overall_pass and r["pass"]

    if args.check_report:
        r = check_report(args.check_report)
        results.append(r)
        overall_pass = overall_pass and r["pass"]

    if not results:
        ap.error("Provide --selftest or at least one --check-* option")

    print(json.dumps({"overall_pass": overall_pass, "results": results}, ensure_ascii=False, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
