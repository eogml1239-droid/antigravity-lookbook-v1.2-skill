#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jacc.py - Jev-Anchored Context Compression runner. (v4 2026-11-18: API 질문 후보 선별·아티팩트 융합 / v3: 단위별 가중 점수·다중 항목·번복 처리·항목 단위 예산 절삭 + 어미·구조 단서, 절 단위 변경 판정)
Zero dependencies. Windows-friendly. Works without TYPESAFE_API_KEY (sim mode).

  py -3 jacc.py --selftest
  py -3 jacc.py --input window.md
  py -3 jacc.py --input window.md --mode api
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, uuid, datetime
import concurrent.futures
import urllib.request, urllib.error

HOME = os.path.expanduser("~")
BASE = os.environ.get("JACC_BASE") or os.path.dirname(os.path.abspath(__file__))
RECORDS = os.path.join(BASE, "records")
CACHE_DIR = os.path.join(BASE, "cache")
STATS = os.path.join(BASE, "stats.jsonl")
LEDGER = os.path.join(BASE, "ledger.jsonl")
ENV_KEY = "TYPESAFE_API_KEY"
API_URL = "https://api.typesafe.ai/v1/systemone"
MIN_SOURCE_TOKENS = 2000      # 이하면 압축을 거부한다
OVERHEAD_FLOOR    = 450       # 구조 바닥 실측(~700tok)을 감안한 허용 오버헤드
BUDGET_RATIO      = 0.10      # 예산 = OVERHEAD_FLOOR + 10% × 소스토큰

def est_tokens(text):
    """보수적 추정. 한글은 len//3 보다 크게 잡힌다."""
    return max(1, len(text) // 2)

TOY_WINDOW = """사용자: src/auth.py 에서 토큰 만료 버그가 나요.
어시스턴트: src/auth.py 44행을 수정했습니다. 예외 처리를 추가했습니다.
사용자: 만료 검사를 미들웨어로 옮기는 걸로 하죠.
어시스턴트: 테스트는 아직 작성하지 않았습니다."""

RE_PATH = re.compile(r'(?<![\w@])([A-Za-z0-9_\-./\\]*[A-Za-z0-9_\-]\.(?:py|pyi|ipynb|js|mjs|cjs|ts|tsx|jsx|vue|svelte|json|jsonl|md|ya?ml|toml|ini|cfg|conf|env|lock|sql|sh|bash|ps1|psm1|bat|cmd|go|rs|java|kt|kts|gradle|rb|php|cs|c|cc|cpp|hpp|h|swift|dart|scala|tf|proto|html?|css|scss|sass|less|csv|tsv|txt|xml|svg|ttf|otf|woff2?|png|jpe?g|gif|webp|pdf|xlsx?|docx?|pptx?|zip))\b')
RE_ERR = re.compile(r'(\b[A-Z]{2,}[-_]\d{2,}\b|\bE\d{3,}\b|0x[0-9A-Fa-f]{4,})')
RE_SECRET = re.compile(
    r'(sk-[A-Za-z0-9_\-]{16,}'
    r'|xox[abposr]-[A-Za-z0-9\-]{10,}'
    r'|gh[pousr]_[A-Za-z0-9]{20,}'
    r'|AKIA[0-9A-Z]{16}'
    r'|AIza[0-9A-Za-z_\-]{30,}'
    r'|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|Bearer\s+[A-Za-z0-9._\-]{16,}'
    r'|(?:password|passwd|pwd|비밀번호|비번|암호)\s*[:=]\s*\S+'
    r'|(?:api[_-]?key|access[_-]?key|secret|token|토큰)\s*[:=]\s*\S+'
    r'|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
    r'|\b01[016789]-?\d{3,4}-?\d{4}\b'
    r'|\b\d{6}-[1-4]\d{6}\b'
    r'|\b(?:\d{4}[- ]){3}\d{4}\b)', re.I)

KW_INTENT = ["하고 싶", "하려고", "하려는", "목표는", "해줘", "해 주세요", "만들", "고쳐", "수정해", "추가해", "원해", "필요해"]
KW_CAUSE = ["때문", "왜냐", "원인", "버그", "오류", "에러", "실패", "안 됨", "안됨"]
KW_HYP = ["아마", "것 같", "듯", "추정", "가설", "maybe", "probably"]
KW_DECIDE = ["하자", "로 한다", "로 하죠", "하기로", "쓰기로", "결정", "채택", "로 정했", "하죠", "해주세요", "할까요"]
KW_NEXT = ["todo", "다음", "남았", "아직", "추후", "이후", "해야", "예정"]
KW_BLOCK = ["물어봐", "확인 필요", "정해 주", "알려 주", "결정해", "선택해"]
KW_ART = ["읽었", "열었", "수정", "편집", "생성", "삭제", "추가했", "변경", "고쳤"]
CHANGE_MAP = [("deleted", ["삭제", "지웠", "removed", "deleted"]),
              ("failed", ["실패", "안 됨", "failed", "error"]),
              ("created", ["생성", "만들", "created", "added"]),
              ("modified", ["수정", "편집", "고쳤", "변경", "추가", "modified", "edited"]),
              ("read", ["읽었", "열었", "read", "opened"]),
              ("mentioned_only", [])]

def now_iso(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
def band_of(s): return "high" if s >= 0.7 else ("low" if s <= 0.3 else "mid")
def hit(text, kws): return sum(1 for k in kws if k.lower() in text.lower())
def score_hits(text, kws, base=0.0, step=0.35, cap=0.95):
    n = hit(text, kws)
    return min(cap, base + step * n) if n else base

def ensure_dirs():
    for d in (BASE, RECORDS): os.makedirs(d, exist_ok=True)

def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(text)

def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

def append_ledger(kind, ref, meta=None):
    ensure_dirs()
    ev = {"e": "e%d" % int(datetime.datetime.now().timestamp() * 1000), "ts": now_iso(), "kind": kind, "ref": ref}
    if meta: ev["meta"] = meta
    with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev["e"]

def ledger_last():
    if not os.path.exists(LEDGER): return None
    last = None
    with open(LEDGER, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: last = line
    return json.loads(last)["e"] if last else None

LINE_SPLIT_CHARS = 300   # 한 줄(한 발화)이 이보다 길 때만 문장 단위로 쪼갠다

def split_units(text):
    """발화(줄) 단위로 자른다. 긴 줄만 문장 단위로 쪼갠다. 모든 단위는 원문 부분 문자열이다."""
    units, n = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        parts = [line] if len(line) <= LINE_SPLIT_CHARS else re.split(r'(?<=[.!?。？！])\s+', line)
        for p in parts:
            p = p.strip()
            if not p: continue
            n += 1
            units.append({"id": "u%d" % n, "text": p})
    return units

# ---- v2 휴리스틱: 단위별 가중 점수 (한국어+영어) ----
RE_ROLE_USER = re.compile(r'^\s*(사용자|유저|user|human|me)\s*[:：]', re.I)
RE_ROLE_AI = re.compile(r'^\s*(어시스턴트|assistant|claude|ai|gemini|gpt|bot)\s*[:：]', re.I)

def role_of(t):
    if RE_ROLE_USER.match(t): return "user"
    if RE_ROLE_AI.match(t): return "ai"
    return "?"

W_INTENT = {"하고 싶": 2, "고치고 싶": 2, "싶어요": 2, "싶습니다": 2, "싶어": 1.5, "해결하고": 1.5, "고쳐 주세요": 2,
            "고쳐줘": 2, "만들어 주세요": 2, "만들어줘": 2, "목표는": 2, "목표:": 2, "해줘": 1, "해 주세요": 0.5,
            "i want": 2, "i'd like": 2, "we need to": 1.5, "please fix": 2, "fix it": 1.5, "goal is": 2,
            "help me": 1.5, "i need": 1.5}
W_PROBLEM = {"문제": 1, "버그": 1, "에러": 1, "오류": 1, "안 바뀌": 1, "멈추": 1, "안 돼": 1,
             "bug": 1, "error": 1, "fails": 1, "broken": 1, "loses": 1, "실패": 1, "느리": 1, "깨": 1,
             "timing out": 1, "timeout": 1, "slow": 1}  # 요청어와 함께 있을 때만 더한다
W_CAUSE = {"원인": 2, "때문": 2, "이유는": 2, "because": 2, "root cause": 2.5, "caused by": 2, "due to": 2,
           "the reason": 2, "터지": 1, "crash": 1, "fails when": 1,
           "버그": 0.3, "오류": 0.3, "에러": 0.3, "bug": 0.3, "error": 0.3}
W_HYP = {"아마": 1, "것 같": 1, "듯": 0.5, "추정": 1, "가설": 1, "것으로 보": 1, "maybe": 1, "probably": 1,
         "likely": 1, "might": 0.5, "seems": 0.5, "i think": 1}
W_DECIDE = {"하기로": 2, "기로 해": 2, "기로 했": 2, "로 하죠": 2, "걸로 하죠": 2, "걸로 해": 2, "결정했": 2,
            "결정:": 2, "채택": 2, "로 정했": 2, "하자": 1.5, "하죠": 1.5, "로 해요": 1.5, "말고": 1.5, "대신": 1.5,
            "let's": 2, "we'll": 2, "we will": 2, "decided": 2, "go with": 2, "instead": 1.5,
            "scratch that": 1.5, "for now": 1, "바꿔 주세요": 1}
W_NEXT = {"다음 할 일": 2.5, "다음에는": 2, "남은 작업": 2.5, "남은 일": 2.5, "next step": 2.5, "todo": 2.5,
          "to do:": 2.5, "remaining": 2, "해야 합니다": 1, "해야 해": 1, "예정": 1, "추후": 1, "나중에": 0.5,
          "next": 1}
# v3: 단어 사전이 아니라 어미·문형(구조) 단서. (정규식, 가중치)
RX_INTENT = [(r"(아|어|여|해|꿔|워|와)야\s*(해|합|함|돼|됩|겠)", 1.5), (r"needs?\s+(to|fixing)\b", 1.5),
             (r"\b(can|could) you\b", 1), (r"\bkeeps?\s+\w+ing\b", 1), (r"\bplease\b", 0.5),
             (r"^\s*(목표|goal|요청|task)\s*[:：]", 2)]
RX_CAUSE = [(r"(?<!에)서\s*(그렇|그런|생기|발생|실패|나|깨)", 2), (r"그래서", 1.5), (r"탓", 1.5),
            (r"(보니|확인 결과|살펴보니)", 1), (r"\bthat'?s (what|why)\b", 2), (r"\bwhich is why\b", 2),
            (r"\b(ignores?|falls? back|is missing|doesn'?t|does not|never)\b", 0.7), (r"\bso\b", 0.5),
            (r"\b(checked|looking at)\b", 0.5)]
RX_DECIDE = [(r"(죠|시다|자|걸로|기로|기로 함|면 됩니다|면 돼요)\s*[.!]?\s*$", 2), (r"(걸로|기로|방향으로)", 1),
             (r"^\s*(user\s*[:：]\s*)?(ok(ay)?,?\s*)?(use|go|keep|hold off|don'?t|do not|no need|switch|drop|stick with|let'?s|skip|avoid)\b", 2)]
RX_NEXT = [(r"(할 일|다음|todo|remaining|next)\s*[:：]", 2.5), (r"다음 단계", 2.5), (r"차례", 2),
           (r"(하|해|보|드리)겠습니다", 1.5), (r"^\s*(assistant\s*[:：]\s*)?will\b", 2), (r"\bwill\b", 0.7),
           (r"\b(going to|plan to)\b", 1)]
RX_GENERIC_PAST = re.compile(r"((었|았|였|했|웠|꿨|뒀|됐)(습니다|어요|다|음)|완료|두었|\b[a-z]{3,}ed\b)", re.I)

def rxscore(t, table):
    return sum(w for rx, w in table if re.search(rx, t, re.I | re.M))

REVOKE = ["말고", "대신", "취소", "바꿔", "instead", "scratch that", "actually", "never mind", "rather than"]
PROPOSE = ["할까요", "shall we", "should we", "how about"]
AFFIRM = re.compile(r'^\s*(?:어시스턴트|assistant|claude|ai)?\s*[:：]?\s*(네|예|좋습니다|알겠습니다|yes|sure|ok|okay)\b', re.I)

ACT_PATTERNS = [  # (change, 완료형 패턴) — 요청형("추가해 주세요")은 잡지 않는다
    ("failed", ["실패", "failed", "error:", "could not", "couldn't"]),
    ("deleted", ["삭제했", "지웠", "deleted", "removed", "dropped"]),
    ("modified", ["수정했", "편집했", "고쳤", "변경했", "추가했", "바꿨", "반영했", "modified", "edited", "updated",
                  "changed", "fixed", "patched", "넣었", "바꿔 두", "고침", "수정 완료",
                  "rewrote", "rewritten"]),
    ("created", ["생성했", "만들었", "작성했", "추가함", "추가 완료", "created", "added", "wrote"]),
    ("read", ["읽었", "읽어", "열었", "확인했", "살펴", "read ", "opened", "looked at", "inspected", "checked", "열어", "보니", "확인 결과", "looking at"]),
]
CHANGE_RANK = {"failed": 5, "deleted": 4, "modified": 3, "created": 2, "read": 1}

def wscore(t, table):
    tl = t.lower()
    return sum(w for k, w in table.items() if k in tl)

def act_kinds(t):
    tl = t.lower()
    ks = [name for name, pats in ACT_PATTERNS if any(p in tl for p in pats)]
    if not ks and re.search(r"(^|\s)추가\s*$", t):
        ks = ["created"]
    return ks

RE_CLAUSE = re.compile(r"\s*(?:,|;|，|\band\b|및|그리고)\s*", re.I)

def path_kinds(unit_text, path):
    """경로가 든 절(쉼표·and·및 기준)의 동작을 먼저 본다. 없으면 발화 전체, 그래도 없으면 일반 과거형=modified(약함)."""
    for cl in RE_CLAUSE.split(unit_text):
        if path in cl:
            ks = act_kinds(cl)
            if ks: return ks, False
    ks = act_kinds(unit_text)
    if ks: return ks, False
    if RX_GENERIC_PAST.search(unit_text):
        return ["modified"], True
    return [], False

_STOP = {"user", "assistant", "the", "and", "for", "with", "that", "this", "사용자", "어시스턴트", "그럼", "그리고",
         "now", "all", "jobs", "next"}

def content_tokens(t):
    t = re.sub(r'^\s*[^:：]{1,12}[:：]', '', t)
    toks = set(w.lower() for w in re.findall(r'[A-Za-z][A-Za-z0-9_\-]{2,}|[가-힣]{2,}', t))
    return {w for w in toks if w not in _STOP}

def unit_scores(units):
    """단위별 섹션 점수. 같은 텍스트가 반복되면 마지막 등장만 남긴다."""
    last = {}
    for i, u in enumerate(units):
        last[u["text"]] = i
    out = []
    n = len(units)
    for i, u in enumerate(units):
        if last[u["text"]] != i:
            continue
        t, r = u["text"], role_of(u["text"])
        q = t.rstrip().endswith("?") or t.rstrip().endswith("？")
        s = {"id": u["id"], "text": t, "role": r, "pos": i / max(n - 1, 1)}
        si = wscore(t, W_INTENT) + rxscore(t, RX_INTENT)
        s["intent"] = (si + (wscore(t, W_PROBLEM) if si else 0)) * (1.0 if r != "ai" else 0.2)
        s["cause"] = (wscore(t, W_CAUSE) + rxscore(t, RX_CAUSE)) * (0.4 if r == "user" else 1.0)
        s["hyp"] = wscore(t, W_HYP)
        d = (wscore(t, W_DECIDE) + rxscore(t, RX_DECIDE)) * (1.0 if r != "ai" else 0.3)
        if q:
            d = 0.0
            if any(p in t.lower() for p in PROPOSE) and i + 1 < n and AFFIRM.match(units[i + 1]["text"]):
                d = 2.0
        s["decision"] = d
        s["next"] = (wscore(t, W_NEXT) + rxscore(t, RX_NEXT)) * (0.8 if r == "user" else 1.0) * (0.0 if q else 1.0)
        s["revoke"] = any(k in t.lower() for k in REVOKE)
        out.append(s)
    return out

def pick_top(scored, key, thr, cap, exclude, prefer="score"):
    c = [s for s in scored if s[key] >= thr and s["id"] not in exclude]
    if prefer == "latest":
        c.sort(key=lambda s: (-s[key], -s["pos"]))
    elif prefer == "earliest":
        c.sort(key=lambda s: (-s[key], s["pos"]))
    else:
        c.sort(key=lambda s: s["pos"])
        return c[:cap]
    return c[:cap]

def pick_candidates(units, limit=40):
    paths, errs, arts = [], [], []
    for u in units:
        for m in RE_PATH.finditer(u["text"]):
            if m.group(1) not in paths: paths.append(m.group(1))
        for m in RE_ERR.finditer(u["text"]):
            if m.group(1) not in errs: errs.append(m.group(1))
        if hit(u["text"], KW_ART): arts.append(u["id"])
    return {"paths": paths[:limit], "errors": errs[:limit], "artifact_units": arts[:limit], "dropped": max(0, len(paths) - limit)}

def sim_signals(units, cands, digest):
    s = {}
    for u in units:
        t = u["text"]
        s["secret__" + u["id"]] = score_hits(t, KW_SECRET_KWS) if False else (0.9 if RE_SECRET.search(t) else 0.05)
    s["intent_present"] = score_hits(" ".join(u["text"] for u in units), KW_INTENT, 0.1)
    s["intent_superseded"] = 0.2 if not digest else score_hits(" ".join(u["text"] for u in units), ["대신", "말고", "취소", "바꿔"], 0.15)
    s["cause_present"] = score_hits(" ".join(u["text"] for u in units), KW_CAUSE, 0.1)
    s["cause_is_hypothesis"] = score_hits(" ".join(u["text"] for u in units), KW_HYP, 0.1)
    s["decision_present"] = score_hits(" ".join(u["text"] for u in units), KW_DECIDE, 0.1)
    s["next_action_present"] = score_hits(" ".join(u["text"] for u in units), KW_NEXT, 0.1)
    s["blocked_on_user"] = score_hits(" ".join(u["text"] for u in units), KW_BLOCK, 0.1)
    s["open_question"] = 0.8 if ("?" in " ".join(u["text"] for u in units) or "궁금" in " ".join(u["text"] for u in units)) else 0.1
    s["off_schema"] = 0.1
    s["artifact_unlisted"] = 0.8 if cands["paths"] else 0.1
    for p in cands["paths"]:
        s["path_is_artifact__" + p] = 0.85
    return s

KW_SECRET_KWS = ["password", "api key", "secret", "token"]

def pick_unit_for(units, kws):
    best, bestn = None, 0
    for u in units:
        n = hit(u["text"], kws)
        if n > bestn: best, bestn = u["id"], n
    return best, band_of(min(0.95, 0.4 + 0.3 * bestn)) if best else (None, "low")

CHANGE_PRIORITY = ["failed", "deleted", "modified", "created", "read", "mentioned_only"]

def change_kind(t):
    for name, kws in CHANGE_MAP:
        if any(k.lower() in t.lower() for k in kws):
            return name
    return "mentioned_only"

def change_kind_units(texts):
    kinds = set()
    for t in texts:
        for name, kws in CHANGE_MAP:
            if any(k.lower() in t.lower() for k in kws):
                kinds.add(name)
    for p in CHANGE_PRIORITY:
        if p in kinds:
            return p
    return "mentioned_only"

def cache_key(state, questions):
    payload = json.dumps({"state": state, "questions": questions}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def load_cache(key):
    path = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            resp = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(resp, dict) and "error" not in resp and isinstance(resp.get("answers"), dict):
        return resp
    return None

def save_cache(key, resp):
    import tempfile

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, key + ".json")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=CACHE_DIR, delete=False
        ) as f:
            temp_path = f.name
            json.dump(resp, f, ensure_ascii=False)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            os.unlink(temp_path)

def call_jev(state, questions, mode, dry=False):
    if dry or mode == "sim":
        return {"emulated": True, "model": "sim", "answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}
    key = os.environ.get(ENV_KEY)
    if not key: return {"emulated": True, "model": "sim", "answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}
    ck = cache_key(state, questions)
    cached = load_cache(ck)
    if cached is not None:
        print(f"CACHE HIT: {ck[:8]}", file=sys.stderr)
        return {**cached, "cache_hit": True}
    body = json.dumps({"model": "jev-latest", "state": state, "questions": questions}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if isinstance(resp, dict) and "error" not in resp and isinstance(resp.get("answers"), dict):
            try:
                save_cache(ck, resp)
            except OSError:
                print("WARN: could not save Jev cache", file=sys.stderr)
        return resp
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:
        return {"error": str(e)}

RE_SECRET_HINT = re.compile(
    r"(\d{4,}|@|[:=]\s*\S{6,}|비번|비밀번호|암호|password|passwd|key|토큰|token|secret|계정|주민|카드|card|"
    r"연락처|전화|phone|주소|address|계좌|account)", re.I)
CHOICE_TOP = 8

def build_questions(state, cands, units):
    idx = {u["id"]: i for i, u in enumerate(units)}
    scored = [x for x in unit_scores(units) if not RE_SECRET.search(x["text"])]

    def crit(key):
        top = sorted([x for x in scored if x[key] > 0], key=lambda x: (-x[key], -x["pos"]))[:CHOICE_TOP]
        top.sort(key=lambda x: x["pos"])
        return {x["id"]: ("`units[%d]`" % idx[x["id"]]) for x in top}

    q = {
        "ambiguity": {"type": "score", "instructions": {"question": "How ambiguous is `units` for extracting intent, cause, artifacts, and decisions?", "inspect": "`units`"}, "criteria": ["Clear and explicit", "Moderately ambiguous", "Very ambiguous or contradictory"]},
        "intent_present": {"type": "noul", "instructions": {"question": "Do `units` state an explicit goal of what the user wants to accomplish?", "inspect": "`units`"}},
        "intent_superseded": {"type": "noul", "instructions": {"question": "Do `units` replace the goal recorded in `digest`?", "compare": ["`units`", "`digest`"]}},
        "cause_present": {"type": "noul", "instructions": {"question": "Do `units` identify a cause for the problem being worked on?", "inspect": "`units`"}},
        "cause_is_hypothesis": {"type": "noul", "instructions": {"question": "Is the stated cause a hypothesis rather than a confirmed finding?", "inspect": "`units`"}},
        "decision_present": {"type": "noul", "instructions": {"question": "Do `units` record a choice that changes future behavior?", "inspect": "`units`"}},
        "next_action_present": {"type": "noul", "instructions": {"question": "Do `units` state a concrete next action?", "inspect": "`units`"}},
        "blocked_on_user": {"type": "noul", "instructions": {"question": "Does the work depend on an answer only the user can give?", "inspect": "`units`"}},
        "open_question": {"type": "noul", "instructions": {"question": "Do `units` leave a question unanswered?", "inspect": "`units`"}},
        "off_schema": {"type": "noul", "instructions": {"question": "Does any high-scoring unit fit none of intent/cause/artifact/decision/next-action?", "inspect": "`units`"}},
    }
    for qid, key, ask in (("intent_unit", "intent", "Which unit states the current intent?"),
                          ("cause_unit", "cause", "Which unit states the root cause?"),
                          ("decision_unit", "decision", "Which unit records the most important decision?"),
                          ("next_action_unit", "next", "Which unit states the next action?")):
        c = crit(key)
        if len(c) >= 2:
            q[qid] = {"type": "choice", "instructions": ask, "criteria": c}
    hints = [(i, u) for i, u in enumerate(units) if RE_SECRET_HINT.search(u["text"])][:40]
    for i, u in hints:
        q["contains_secret__" + u["id"]] = {"type": "noul", "instructions": {"question": "Does `units[%d]` contain a password, API key, token, or personal identifier?" % i}}
    for p in cands["paths"]:
        q["path_is_artifact__" + p] = {
            "type": "noul",
            "instructions": {
                "question": "Do `units` depend on the artifact `%s`?" % p,
                "inspect": "`units`",
                "focus": "True only if the path is read, written, or depended on — not merely mentioned."
            }
        }
        q["artifact_change__" + hashlib.md5(p.encode("utf-8")).hexdigest()[:8]] = {"type": "choice",
            "instructions": {"question": "What happened to the artifact `%s` in `units`?" % p, "inspect": "`units`"},
            "criteria": {"read": "Only opened or read.", "created": "Newly created.",
                         "modified": "Edited or changed.", "deleted": "Removed.",
                         "failed": "Attempted and failed.", "mentioned_only": "Named without action."}}
    return q

def normalize(resp, mode):
    out = {"_emulated": resp.get("emulated", mode == "sim")}
    for k, v in (resp.get("answers") or {}).items():
        if isinstance(v, dict):
            if "noul" in v: out[k] = {"score": float(v["noul"]), "value": float(v["noul"]) >= 0.5}
            elif "choice" in v: out[k] = {"value": v["choice"], "score": float(v.get("confidence", 0.5))}
            elif "score" in v:
                score = v["score"] if k == "ambiguity" else v.get("confidence", 0.5)
                out[k] = {"value": v["score"], "score": float(score)}
        elif isinstance(v, (int, float)):
            out[k] = {"score": float(v), "value": float(v) >= 0.5}
    return out

SEC_LIMITS = {"intent": (1.5, 1), "cause": (1.0, 2), "decision": (1.5, 6), "next": (1.5, 2)}

def assemble(units, cands, sigs, digest, mode, ledger_from, turn=0):
    umap = {u["id"]: u["text"] for u in units}

    def sc(key, default=0.0):
        return sigs.get(key, {}).get("score", default)

    def secret_score(uid, text):
        rx = 0.9 if RE_SECRET.search(text) else 0.05
        for k in ("contains_secret__" + uid, "secret__" + uid):
            if k in sigs:
                return max(sigs[k].get("score", 0.0), rx)  # 정규식에 걸리면 API 점수와 무관하게 가린다
        return rx

    ambiguity = sc("ambiguity", 0.0)
    marker_threshold = 0.8 if ambiguity >= 1.0 else 0.7
    art_threshold = 0.2 if ambiguity >= 1.0 else 0.3

    rec = {"schema": "jacc/1", "mode": mode,
           "compressed_at": {"turn": turn, "unit_count": len(units),
                             "event_range": [ledger_from or "", ledger_last() or ""]},
           "intent": [], "intent_history": [], "root_cause": [], "artifacts": [], "decisions": [],
           "open": {"next_actions": [], "blocked_on_user": sc("blocked_on_user") >= 0.7, "questions": []},
           "misc": [], "redactions": [], "parked": [], "superseded": [],
           "probe": {"content": "", "artifact": ""},
           "ledger_pointer": {"file": "ledger.jsonl", "last": ledger_last() or ""},
           "emulated": mode == "sim"}

    redacted = []
    for u in units:
        if secret_score(u["id"], u["text"]) >= 0.3:
            redacted.append(u["id"])
    rec["redactions"] = redacted
    red = set(redacted)

    scored = [s for s in unit_scores(units) if s["id"] not in red]

    def gate(present_key):
        # api: Jev noul 이 0.3 이하이면 섹션을 비운다. sim: 단위 점수만으로 판단.
        return mode == "sim" or sc(present_key, 1.0) > 0.3

    def item(s, key, present_key, extra=None):
        it = {"text": s["text"], "unit": s["id"]}
        conf = min(0.95, 0.45 + 0.15 * s[key])
        if mode == "sim":
            it["band"] = band_of(conf)
        else:
            conf = sc(present_key, conf)
            it["noul"] = round(conf, 2)
        if conf < marker_threshold:
            it["marker"] = "[미확정]"
        if extra: it.update(extra)
        return it

    def api_choice(key):
        v = sigs.get(key, {})
        val = v.get("value")
        if mode != "sim" and isinstance(val, str) and val in umap and val not in red and v.get("score", 0) >= 0.6:
            return by_text.get(umap[val], val)  # 반복 발화면 마지막 등장 id 로 맞춘다
        return None

    used = set()
    by_id = {s["id"]: s for s in scored}
    by_text = {s["text"]: s["id"] for s in scored}

    def take(sec_key, present_key, choice_key, prefer, out_list, extra_fn=None):
        if not gate(present_key):
            return
        thr, cap = SEC_LIMITS[sec_key]
        picks = pick_top(scored, sec_key, thr, cap, used, prefer)
        ch = api_choice(choice_key)
        if ch and ch not in [p["id"] for p in picks] and ch in by_id and ch not in used:
            picks = [by_id[ch]] + picks[:cap - 1]
        for s in picks:
            used.add(s["id"])
            out_list.append(item(s, sec_key, present_key, extra_fn(s) if extra_fn else None))

    take("intent", "intent_present", "intent_unit", "earliest", rec["intent"])
    if not rec["intent"] and gate("intent_present"):
        # 의도는 비우지 않는다: 임계값 미만이라도 가장 이른 요청 발화를 [미확정]으로 남긴다
        weak = pick_top(scored, "intent", 0.5, 1, used, "earliest")
        for s in weak:
            used.add(s["id"]); it = item(s, "intent", "intent_present"); it["marker"] = "[미확정]"
            rec["intent"].append(it)
    hyp_api = sc("cause_is_hypothesis", -1)
    take("cause", "cause_present", "cause_unit", "score", rec["root_cause"],
         lambda s: {"state": "hypothesis" if (hyp_api >= 0.7 if hyp_api >= 0 else s["hyp"] >= 1) else "confirmed"})
    decs = []
    take("decision", "decision_present", "decision_unit", "score", decs, lambda s: {"scope": "unclear"})
    # 번복(말고/대신/instead/scratch that…) 결정이 앞선 결정과 내용 토큰을 공유하면 앞선 것을 superseded 로 옮긴다
    live = []
    for d in decs:
        s = by_id.get(d["unit"])
        if s and s["revoke"]:
            toks = content_tokens(d["text"])
            keep = []
            for old in live:
                if toks & content_tokens(old["text"]):
                    rec["superseded"].append({"text": old["text"], "unit": old["unit"], "superseded_by": d["unit"]})
                else:
                    keep.append(old)
            live = keep
        live.append(d)
    rec["decisions"] = live
    take("next", "next_action_present", "next_action_unit", "latest", rec["open"]["next_actions"])

    # 아티팩트: 완료형 동작이 붙은 경로만. 단순 언급은 제외(API 가 0.7 이상으로 의존한다고 하면 포함).
    for p in cands["paths"]:
        srcs = [u for u in units if p in u["text"] and u["id"] not in red]
        kinds = []
        ev = None
        weak_only = True
        for u in srcs:
            ks, weak = path_kinds(u["text"], p)
            if ks and not weak: weak_only = False
            if ks:
                kinds += ks
                best_k = max(ks, key=lambda k: CHANGE_RANK[k])
                if ev is None or CHANGE_RANK[best_k] >= CHANGE_RANK[ev[0]]:
                    ev = (best_k, u)
        api_s = sc("path_is_artifact__" + p, -1)
        rule = (0.6 if weak_only else 0.85) if kinds else 0.2
        if mode == "sim" or api_s < 0:
            score = rule
        elif kinds and not weak_only:
            score = max(rule, api_s)            # 완료형 동작이 원문에 있으면 API 점수가 낮아도 포함
        elif kinds:
            score = max(rule, api_s) if api_s >= 0.5 else min(rule, api_s)
        else:
            score = api_s
        if score < art_threshold or (not kinds and score < 0.7) or (kinds and weak_only and score < 0.5):
            if p not in rec["parked"]: rec["parked"].append(p)
            continue
        qid = "artifact_change__" + hashlib.md5(p.encode("utf-8")).hexdigest()[:8]
        api_kind = sigs.get(qid, {}).get("value")
        if (isinstance(api_kind, str) and api_kind in CHANGE_RANK and sigs.get(qid, {}).get("score", 0) >= 0.8
                and (not kinds or weak_only)):
            kind = api_kind
        else:
            kind = max(kinds, key=lambda k: CHANGE_RANK[k]) if kinds else "mentioned_only"
        art = {"path": p, "change": kind, "unit": (ev[1]["id"] if ev else srcs[0]["id"]) if srcs else "",
               "anchor": hashlib.sha1(p.encode("utf-8")).hexdigest()[:12]}
        if ev:
            art["evidence"] = [{"unit": ev[1]["id"], "text": ev[1]["text"]}]
        if score < marker_threshold:
            art["marker"] = "[미확정]"
        if mode == "sim":
            art["band"] = band_of(score)
        else:
            art["confidence"] = round(score, 2)
        rec["artifacts"].append(art)
    rec["artifacts"].sort(key=lambda a: -CHANGE_RANK.get(a["change"], 0))

    # parked: 임계값 근처에서 탈락한 후보(재승격용) — 전체 단위 목록이 아니다
    for s in scored:
        if s["id"] in used: continue
        if max(s["intent"], s["cause"], s["decision"], s["next"]) >= 1.0:
            rec["parked"].append(s["id"])
    rec["parked"] = rec["parked"][:20]
    return rec

def probe_record(rec, ambiguity=0.0):
    have_content = bool(rec["intent"] or rec["artifacts"] or rec["decisions"] or rec["open"]["next_actions"])
    have_art = all(a.get("path") and a.get("change") for a in rec["artifacts"])
    content = "high" if have_content else "low"
    if have_content and not rec["decisions"] and not rec["open"]["next_actions"]: content = "mid"
    if ambiguity >= 1.0 and content == "high":
        content = "mid"
    art = "high" if have_art else ("mid" if rec["artifacts"] else "high")
    rec["probe"]["content"], rec["probe"]["artifact"] = content, art
    return rec

def slim(rec):
    for k in ("intent_history", "misc", "redactions", "parked", "superseded", "trimmed"):
        if k in rec and isinstance(rec[k], list) and not rec[k]:
            del rec[k]
    for a in rec.get("artifacts", []):
        if "evidence" in a and not a["evidence"]:
            del a["evidence"]
        if "unit" in a and not a["unit"]:
            del a["unit"]
    o = rec.get("open")
    if isinstance(o, dict) and not o.get("questions"):
        o.pop("questions", None)
    return rec


def prune_to_budget(rec, budget_tok):
    """예산 초과 시 덜 중요한 것부터 한 항목씩 뺀다. intent 와 redactions 는 건드리지 않는다."""
    def size(r):
        return est_tokens(json.dumps(r, ensure_ascii=False, separators=(",", ":")))

    rec = slim(rec)
    for k in ("misc", "parked", "trimmed", "intent_history", "superseded"):
        if size(rec) <= budget_tok: return rec
        rec.pop(k, None)
    o = rec.get("open") if isinstance(rec.get("open"), dict) else {"next_actions": []}

    def drop_one():
        arts = rec.get("artifacts", [])
        # 1) 읽기만 한 아티팩트, 2) 근거 문장, 3) 각 섹션의 꼬리, 4) 각 섹션의 마지막 1개
        reads = [a for a in arts if a.get("change") == "read"]
        if reads and len(arts) > 1:
            arts.remove(reads[-1]); return True
        for a in reversed(arts):
            if a.get("evidence"):
                a.pop("evidence"); return True
        for lst in (o.get("next_actions", []), rec.get("decisions", []), rec.get("root_cause", []), arts):
            if len(lst) > 1:
                lst.pop(); return True
        for lst in (arts, o.get("next_actions", []), rec.get("root_cause", []), rec.get("decisions", [])):
            if lst:
                lst.pop(); return True
        return False

    while size(rec) > budget_tok and drop_one():
        pass
    return rec

def enforce_budget(rec, budget_tok):
    def size(r):
        return est_tokens(json.dumps(r, ensure_ascii=False, separators=(",", ":")))

    rec["budget"] = {"record_tokens": size(rec) + budget_tok, "budget_tokens": budget_tok, "over": False}
    rec = prune_to_budget(rec, budget_tok)
    budget = rec["budget"]
    budget["record_tokens"] = size(rec)
    budget["over"] = budget["record_tokens"] > budget_tok
    budget["record_tokens"] = size(rec)
    return rec

def run(text, mode, out_path, digest=None, turn=0, *, chunk_units=None, chunk_signals=None):
    if chunk_units is None:
        ensure_dirs()
    units = split_units(text) if chunk_units is None else chunk_units
    cands = pick_candidates(units)
    state = {"digest": digest or {}, "units": [u["text"] for u in units]}
    questions = build_questions(state, cands, units)
    resp = call_jev(state, questions, mode, dry=(mode == "sim"))
    sigs = ({k: {"score": v, "value": v >= 0.5} for k, v in sim_signals(units, cands, digest).items()} if mode == "sim" else
            {k: v for k, v in normalize(resp, mode).items() if not k.startswith("_")})
    rec = assemble(units, cands, sigs, digest or {}, mode, ledger_last(), turn=turn)
    if chunk_units is None and digest is not None and "error" not in resp:
        rec = merge_records(digest, rec)
    ambiguity = sigs.get("ambiguity", {}).get("score", 0.0)
    rec = probe_record(rec, ambiguity)
    src_tok = est_tokens(text)
    budget = OVERHEAD_FLOOR + int(BUDGET_RATIO * src_tok)
    usage = resp.get("usage") or {}
    if resp.get("cache_hit"):
        rec["cache_hit"] = True
    if usage.get("input_tokens") and not resp.get("cache_hit"):
        rec["cost"] = {
            "request_input_tokens": usage.get("input_tokens"),
            "request_output_tokens": usage.get("output_tokens"),
        }
    rec = enforce_budget(rec, budget)
    if chunk_units is None:
        write_json(out_path, rec)
        append_ledger("write", os.path.basename(out_path), {"units": len(units)})
        if "error" not in resp:
            append_stats(rec, mode, src_tok, sigs)
    if chunk_signals is not None:
        chunk_signals.update(sigs)
    return rec, resp

def merge_records(old, new):
    import copy
    merged = copy.deepcopy(new)

    def dedup(items, key_fn):
        seen = set()
        out = []
        for it in items:
            k = key_fn(it)
            if k not in seen:
                seen.add(k)
                out.append(copy.deepcopy(it))
        return out

    merged["intent"] = dedup(old.get("intent", []) + new.get("intent", []), lambda x: x.get("text", ""))
    merged["root_cause"] = dedup(old.get("root_cause", []) + new.get("root_cause", []), lambda x: x.get("text", ""))
    merged["decisions"] = dedup(old.get("decisions", []) + new.get("decisions", []), lambda x: x.get("text", ""))
    merged["artifacts"] = dedup(
        old.get("artifacts", []) + new.get("artifacts", []),
        lambda x: (x.get("path", ""), x.get("change", "")),
    )

    old_open = old.get("open", {})
    new_open = new.get("open", {})
    merged["open"] = {
        "next_actions": dedup(old_open.get("next_actions", []) + new_open.get("next_actions", []), lambda x: x.get("text", "")),
        "blocked_on_user": old_open.get("blocked_on_user", False) or new_open.get("blocked_on_user", False),
        "questions": copy.deepcopy(old_open.get("questions", []) + new_open.get("questions", [])),
    }

    history = old.get("intent_history", [])
    if new.get("intent"):
        history = old.get("intent", []) + history
    if history:
        merged["intent_history"] = dedup(history, lambda x: x.get("text", ""))

    return merged

def split_into_chunks(text, max_tokens=32000, overlap_tokens=3200):
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("overlap_tokens must be non-negative and less than max_tokens")
    max_chars = max_tokens * 2
    overlap_chars = overlap_tokens * 2
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars
    return chunks

def run_chunked(text, mode, out_path, digest=None, turn=0):
    chunks = split_into_chunks(text)
    if not chunks:
        return run(text, mode, out_path, digest, turn)

    chunk_units = []
    unit_count = 0
    for chunk in chunks:
        units = split_units(chunk)
        for index, unit in enumerate(units, start=unit_count + 1):
            unit["id"] = f"u{index}"
        unit_count += len(units)
        chunk_units.append(units)

    chunk_signals = [{} for _ in chunks]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(run, chunk, mode, None, digest, turn, chunk_units=units, chunk_signals=signals)
            for chunk, units, signals in zip(chunks, chunk_units, chunk_signals)
        ]
        results = [future.result() for future in futures]

    for _, response in results:
        if "error" in response:
            return None, response

    records = [record for record, _ in results]
    merged = dict(records[0])
    for record in records[1:]:
        merged = merge_records(merged, record)
    if digest is not None:
        merged = merge_records(digest, merged)

    merged["compressed_at"] = {**merged["compressed_at"], "unit_count": unit_count}
    merged["redactions"] = list(dict.fromkeys(
        unit for record in records for unit in record.get("redactions", [])
    ))
    merged.pop("budget", None)
    merged.pop("cost", None)
    merged.pop("cache_hit", None)
    costs = [record["cost"] for record in records if "cost" in record]
    if costs:
        merged["cost"] = {
            name: sum(cost.get(name) or 0 for cost in costs)
            for name in ("request_input_tokens", "request_output_tokens")
        }
    if all(record.get("cache_hit") for record in records):
        merged["cache_hit"] = True

    ambiguity = max(
        normalize(response, mode).get("ambiguity", {}).get("score", 0.0)
        for _, response in results
    )
    merged = probe_record(merged, ambiguity)
    merged = enforce_budget(merged, OVERHEAD_FLOOR + int(BUDGET_RATIO * est_tokens(text)))

    for index, record in enumerate(records):
        write_json(f"{out_path}.chunk{index}", record)
    write_json(out_path, merged)
    append_ledger("write", os.path.basename(out_path), {"units": unit_count, "chunks": len(chunks)})
    question_scores = {}
    for signals in chunk_signals:
        for key, signal in signals.items():
            if not key.startswith("_") and "__" not in key:
                question_scores.setdefault(key, []).append(signal["score"])
    rolled_up = {
        key: {"score": sum(scores) / len(scores)}
        for key, scores in question_scores.items()
    }
    append_stats(merged, mode, est_tokens(text), rolled_up)
    return merged, results[0][1]

def append_stats(rec, mode, src_tok, sigs):
    ensure_dirs()
    row = {
        "ts": now_iso(),
        "mode": mode,
        "src_tok": src_tok,
        "record_tok": rec.get("budget", {}).get("record_tokens"),
        "budget_tok": rec.get("budget", {}).get("budget_tokens"),
        "probe": rec.get("probe"),
        "n_artifacts": len(rec.get("artifacts", [])),
        "n_decisions": len(rec.get("decisions", [])),
        "n_parked": len(rec.get("parked", [])),
        "questions": {k: round(v.get("score", 0.0), 3) for k, v in sigs.items()
                      if isinstance(v, dict) and not k.startswith("_") and "__" not in k},
    }
    with open(STATS, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def print_stats():
    if not os.path.exists(STATS):
        print("NO_STATS"); return
    rows = [json.loads(l) for l in open(STATS, encoding="utf-8") if l.strip()]
    print(f"runs: {len(rows)}")
    qkeys = set()
    for r in rows:
        qkeys.update(r.get("questions", {}).keys())
    print("--- per-question confidence ---")
    for q in sorted(qkeys):
        vals = [r["questions"][q] for r in rows if q in r.get("questions", {})]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        amb = sum(1 for v in vals if 0.3 < v < 0.7)
        print(f"{q}: n={len(vals)} mean={mean:.2f} ambiguous={amb}/{len(vals)}")
    print("--- compression ---")
    ratios = [r["record_tok"] / r["src_tok"] for r in rows
              if r.get("record_tok") and r.get("src_tok") and r["src_tok"] >= MIN_SOURCE_TOKENS]
    excluded = sum(1 for r in rows if r.get("src_tok") and r["src_tok"] < MIN_SOURCE_TOKENS)
    if ratios:
        print(f"ratio mean={sum(ratios)/len(ratios):.1%} min={min(ratios):.1%} max={max(ratios):.1%} (n={len(ratios)}, excluded={excluded})")
    else:
        print(f"ratio: no eligible runs (excluded={excluded} below MIN_SOURCE_TOKENS)")
    print("--- suggestions ---")
    for q in sorted(qkeys):
        vals = [r["questions"][q] for r in rows if q in r.get("questions", {})]
        if len(vals) >= 5 and all(0.3 < v < 0.7 for v in vals):
            print(f"PRUNE CANDIDATE: {q} (always ambiguous, {len(vals)} runs)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input"); ap.add_argument("--out"); ap.add_argument("--mode", default="auto", choices=["auto", "api", "sim"])
    ap.add_argument("--selftest", action="store_true"); ap.add_argument("--merge")
    ap.add_argument("--turn", type=int, default=0)
    ap.add_argument("--chunked", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        print_stats(); return 0
    mode = a.mode
    if mode == "auto": mode = "api" if os.environ.get(ENV_KEY) else "sim"
    text = TOY_WINDOW
    digest = None
    if a.selftest:
        out = os.path.join(RECORDS, "selftest.json"); mode = "sim"
    else:
        if not a.input: print("ERROR: --input 필요", file=sys.stderr); return 2
        with open(a.input, "r", encoding="utf-8-sig") as f: text = f.read()
        _t = est_tokens(text)
        if _t < MIN_SOURCE_TOKENS:
            print(json.dumps({"skipped": True, "reason": "below_min_source_tokens",
                              "source_tokens": _t, "min": MIN_SOURCE_TOKENS},
                             ensure_ascii=False))
            return 0
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = a.out or os.path.join(RECORDS, "jacc-%s.json" % ts)
        if a.merge and os.path.exists(a.merge):
            with open(a.merge, "r", encoding="utf-8-sig") as f: digest = json.load(f)
    if a.chunked or est_tokens(text) > 64000:
        rec, resp = run_chunked(text, mode, out, digest, turn=a.turn)
    else:
        rec, resp = run(text, mode, out, digest, turn=a.turn)
    if rec is None:
        print("API ERROR:", resp.get("error"), str(resp.get("body", ""))[:200], file=sys.stderr)
        return 3
    if a.selftest:
        req = ["schema", "mode", "intent", "root_cause", "artifacts", "decisions", "open", "probe", "emulated"]
        missing = [k for k in req if k not in rec]
        bad = [x["path"] for x in rec["artifacts"] if not x.get("anchor")]
        if missing or bad:
            print("SELFTEST FAIL:", missing, bad, file=sys.stderr); return 2
        print("SELFTEST OK ->", out); print(json.dumps(rec, ensure_ascii=False, indent=2)[:800]); return 0
    nt = est_tokens(text)
    mt = rec.get("budget", {}).get("record_tokens",
             est_tokens(json.dumps(rec, ensure_ascii=False, separators=(",", ":"))))
    print("JACC: %dtok -> %dtok (%.1f%%) | mode=%s | probe=%s/%s | budget=%s" % (
        nt, mt, 100.0 * mt / max(nt, 1), mode,
        rec["probe"]["content"], rec["probe"]["artifact"],
        "over" if rec.get("budget", {}).get("over") else "ok"))
    print("RECORD:", out)
    if "error" in (resp or {}): print("API ERROR:", resp.get("error"), str(resp.get("body", ""))[:200], file=sys.stderr); return 3
    return 0

if __name__ == "__main__":
    sys.exit(main())
