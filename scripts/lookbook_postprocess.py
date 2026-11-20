#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lookbook_postprocess.py - Tier 0 (0-token) Lookbook Asset Organizer, Watermark Remover, Platform Resizer & Prompt Patch DB.

Uses local Python (OpenCV + Pillow + NumPy) with 0 LLM tokens:
  1. --init-product "<상품명>": Create standard YYYY년 MM월 DD일 <상품명> folder tree + register in _INDEX.md
  2. --export-approved "<img_path>" --product-dir "<dir>": Remove Gemini star watermark (OpenCV) + export 3 platform sizes
     (Naver 1000x1000, KakaoStyle 1080x1296, Ably 900x1080) with objective dimension/byte/SHA256 verification
  3. --patch-get "<error_code>" / --patch-add: Query or accumulate AI-to-AI prompt_patches.json
  4. --find "<keyword>": Instant 0-token search across Antigravity_산출물 and _INDEX.md
  5. --selftest: Deterministic end-to-end verification in a temporary directory
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image

JACC_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_ROOT = os.path.dirname(JACC_DIR)  # G:\내 드라이브\Antigravity_산출물
INDEX_PATH = os.path.join(STORAGE_ROOT, "_INDEX.md")
PATCH_DB_PATH = os.path.join(JACC_DIR, "prompt_patches.json")

STANDARD_SUBDIRS = [
    "01_상품속성_사이즈표",
    "02_룩북이미지",
    "03_상세페이지_배너",
    os.path.join("04_플랫폼별_룩북이미지", "네이버_스마트스토어_1000x1000"),
    os.path.join("04_플랫폼별_룩북이미지", "카카오스타일_1080x1296"),
    os.path.join("04_플랫폼별_룩북이미지", "에이블리_900x1080"),
]

PLATFORM_SPECS = [
    ("네이버_스마트스토어_1000x1000", (1000, 1000), "pad_or_crop"),
    ("카카오스타일_1080x1296", (1080, 1296), "cover"),
    ("에이블리_900x1080", (900, 1080), "cover"),
]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def init_product_folder(product_name: str, root: str = STORAGE_ROOT, update_index: bool = True) -> dict:
    today = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    base_name = f"{today} {product_name.strip()}"
    target_dir = os.path.join(root, base_name)
    idx = 2
    while os.path.exists(target_dir):
        target_dir = os.path.join(root, f"{base_name} ({idx})")
        idx += 1

    created = []
    for sub in STANDARD_SUBDIRS:
        p = os.path.join(target_dir, sub)
        os.makedirs(p, exist_ok=True)
        created.append(p)

    folder_label = os.path.basename(target_dir)
    if update_index and os.path.isfile(INDEX_PATH):
        line = f"- [{folder_label}](<{folder_label}/>) — 상품·룩북 프로젝트 표준 폴더 (01~04 자동 생성)\n"
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            existing = f.read()
        if folder_label not in existing:
            with open(INDEX_PATH, "a", encoding="utf-8", newline="\n") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(line)

    return {
        "action": "init_product",
        "product_dir": target_dir,
        "subdirs_created": len(created),
        "index_updated": update_index and os.path.isfile(INDEX_PATH),
    }


def remove_gemini_star_watermark(img_bgr: np.ndarray) -> tuple[np.ndarray, dict]:
    """Search bottom-right 260x260 region for bright star watermark and inpaint via OpenCV."""
    h, w = img_bgr.shape[:2]
    roi_size = min(260, h // 3, w // 3)
    if roi_size < 32:
        return img_bgr, {"watermark_detected": False, "mask_pixels": 0}

    y0, x0 = h - roi_size, w - roi_size
    roi = img_bgr[y0:h, x0:w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Local background estimate via median blur
    bg = cv2.medianBlur(gray, 31)
    diff = cv2.subtract(gray, bg)
    _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)

    # Keep components located in the bottom-right corner quadrant (typical Gemini star)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    mask_roi = np.zeros_like(gray)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        cx, cy = centroids[i]
        if 40 <= area <= 12000 and cx > roi_size * 0.35 and cy > roi_size * 0.35:
            mask_roi[labels == i] = 255

    mask_pixels = int(np.count_nonzero(mask_roi))
    if mask_pixels == 0:
        return img_bgr, {"watermark_detected": False, "mask_pixels": 0}

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask_roi = cv2.dilate(mask_roi, kernel, iterations=2)
    inpainted_roi = cv2.inpaint(roi, mask_roi, 5, cv2.INPAINT_TELEA)

    out = img_bgr.copy()
    out[y0:h, x0:w] = inpainted_roi
    return out, {"watermark_detected": True, "mask_pixels": mask_pixels}


def resize_cover(pil_img: Image.Image, target_wh: tuple[int, int]) -> Image.Image:
    tw, th = target_wh
    sw, sh = pil_img.size
    scale = max(tw / sw, th / sh)
    nw, nh = int(round(sw * scale)), int(round(sh * scale))
    resized = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def resize_pad_square(pil_img: Image.Image, target_wh: tuple[int, int]) -> Image.Image:
    """For 1:1 Naver SmartStore: preserve full 5:6 garment without cutting hem/lips by sampling studio edge gray."""
    tw, th = target_wh
    sw, sh = pil_img.size
    scale = min(tw / sw, th / sh)
    nw, nh = int(round(sw * scale)), int(round(sh * scale))
    resized = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)

    arr = np.array(pil_img.convert("RGB"))
    edge_samples = np.concatenate([arr[:, 0, :], arr[:, -1, :]], axis=0)
    bg_rgb = tuple(int(v) for v in np.median(edge_samples, axis=0))

    canvas = Image.new("RGB", (tw, th), bg_rgb)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def export_approved(image_path: str, product_dir: str, naver_mode: str = "pad") -> dict:
    # OpenCV unicode-safe read
    data = np.fromfile(image_path, dtype=np.uint8)
    img_bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError(f"Cannot decode image: {image_path}")

    stem = os.path.splitext(os.path.basename(image_path))[0]
    wm_dir = os.path.join(product_dir, "02_룩북이미지", "워터마크제거")
    os.makedirs(wm_dir, exist_ok=True)

    clean_bgr, wm_info = remove_gemini_star_watermark(img_bgr)
    clean_path = os.path.join(wm_dir, f"{stem}_clean.png")
    ok, buf = cv2.imencode(".png", clean_bgr)
    if not ok:
        raise RuntimeError("Failed to encode clean PNG")
    buf.tofile(clean_path)

    pil_clean = Image.fromarray(cv2.cvtColor(clean_bgr, cv2.COLOR_BGR2RGB))
    outputs = []
    for sub, (tw, th), mode in PLATFORM_SPECS:
        out_dir = os.path.join(product_dir, "04_플랫폼별_룩북이미지", sub)
        os.makedirs(out_dir, exist_ok=True)
        if mode == "pad_or_crop" and naver_mode == "pad":
            res_img = resize_pad_square(pil_clean, (tw, th))
        else:
            res_img = resize_cover(pil_clean, (tw, th))
        out_path = os.path.join(out_dir, f"{stem}_{tw}x{th}.jpg")
        res_img.save(out_path, format="JPEG", quality=95, subsampling=0)
        with Image.open(out_path) as check_im:
            actual_w, actual_h = check_im.size
        outputs.append({
            "platform_dir": sub,
            "path": out_path,
            "expected": [tw, th],
            "actual": [actual_w, actual_h],
            "dimension_match": (actual_w == tw and actual_h == th),
            "bytes": os.path.getsize(out_path),
            "sha256": sha256_file(out_path),
        })

    all_match = all(o["dimension_match"] and o["bytes"] > 0 for o in outputs)
    return {
        "action": "export_approved",
        "pass": all_match,
        "source": image_path,
        "clean_path": clean_path,
        "watermark": wm_info,
        "outputs": outputs,
    }


def patch_get(code: str) -> dict:
    with open(PATCH_DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    if code == "all":
        return {"action": "patch_get", "codes": list(db["patches"].keys()), "count": len(db["patches"])}
    entry = db["patches"].get(code)
    return {"action": "patch_get", "code": code, "found": entry is not None, "patch": entry}


def patch_add(code: str, label: str, add_prompt: str, add_negative: str) -> dict:
    with open(PATCH_DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    prev = db["patches"].get(code, {})
    db["patches"][code] = {
        "label": label,
        "add_prompt": add_prompt,
        "add_negative": add_negative,
        "hits": int(prev.get("hits", 0)) + 1,
    }
    db["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(PATCH_DB_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"action": "patch_add", "code": code, "total_patches": len(db["patches"])}


def find_assets(keyword: str, root: str = STORAGE_ROOT) -> dict:
    kw = keyword.lower()
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            if kw in d.lower():
                hits.append({"type": "dir", "path": os.path.join(dirpath, d)})
        for fn in filenames:
            if kw in fn.lower():
                hits.append({"type": "file", "path": os.path.join(dirpath, fn)})
        if len(hits) >= 50:
            break
    return {"action": "find", "keyword": keyword, "count": len(hits), "hits": hits[:50]}


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        # 1. Init product structure
        init_res = init_product_folder("테스트상품", root=td, update_index=False)
        assert init_res["subdirs_created"] == 6

        # 2. Create synthetic 5:6 image (1000x1200) with a bright star-like mark at bottom-right
        img = np.full((1200, 1000, 3), 185, dtype=np.uint8)
        cv2.circle(img, (930, 1130), 22, (250, 250, 250), -1)
        src_img = os.path.join(td, "sample_lookbook.png")
        ok, buf = cv2.imencode(".png", img)
        assert ok
        buf.tofile(src_img)

        # 3. Export approved & verify watermark detection + all 3 platform resolutions
        exp_res = export_approved(src_img, init_res["product_dir"])
        assert exp_res["pass"] is True
        assert exp_res["watermark"]["watermark_detected"] is True
        assert len(exp_res["outputs"]) == 3

        # 4. Patch DB read check
        p_res = patch_get("horizon_line")
        assert p_res["found"] is True

        # 5. Find check
        f_res = find_assets("1080x1296", root=td)
        assert f_res["count"] >= 1

    print(json.dumps({
        "selftest": "PASS",
        "subdirs_created": init_res["subdirs_created"],
        "watermark_detected": exp_res["watermark"]["watermark_detected"],
        "watermark_mask_pixels": exp_res["watermark"]["mask_pixels"],
        "exported_sizes": [o["actual"] for o in exp_res["outputs"]],
        "patch_db_ok": p_res["found"],
        "find_hits": f_res["count"],
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tier 0 Lookbook Postprocess & Prompt Patch DB")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--init-product", type=str, default="")
    ap.add_argument("--export-approved", type=str, default="")
    ap.add_argument("--product-dir", type=str, default="")
    ap.add_argument("--naver-mode", choices=["pad", "crop"], default="pad")
    ap.add_argument("--patch-get", type=str, default="")
    ap.add_argument("--patch-add", nargs=4, metavar=("CODE", "LABEL", "ADD_PROMPT", "ADD_NEG"))
    ap.add_argument("--find", type=str, default="")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.init_product:
        print(json.dumps(init_product_folder(args.init_product), ensure_ascii=False, indent=2))
        return 0
    if args.export_approved:
        if not args.product_dir:
            ap.error("--product-dir is required with --export-approved")
        res = export_approved(args.export_approved, args.product_dir, naver_mode=args.naver_mode)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["pass"] else 1
    if args.patch_get:
        print(json.dumps(patch_get(args.patch_get), ensure_ascii=False, indent=2))
        return 0
    if args.patch_add:
        print(json.dumps(patch_add(*args.patch_add), ensure_ascii=False, indent=2))
        return 0
    if args.find:
        print(json.dumps(find_assets(args.find), ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
