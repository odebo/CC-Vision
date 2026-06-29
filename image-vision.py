#!/usr/bin/env python3
"""
Claude Code Vision Hook
=======================

A UserPromptSubmit hook for Claude Code that gives non-multimodal main models
(such as GLM, DeepSeek, Qwen-Text, etc.) the ability to "see" images pasted
into the chat. When the user submits a message containing one or more images,
this hook:

  1. Detects newly cached images under ~/.claude/image-cache/
  2. Calls a multimodal LLM (any OpenAI-compatible endpoint) to parse each image
  3. Injects the parsed text back into the main model's context via
     `additionalContext`

The main model never sees the pixels — it sees a textual description of the
image, which is enough for almost all follow-up tasks.

Features:
  - Parallel parsing: multiple images are parsed concurrently (configurable workers)
  - Content-hash dedup: same image at different paths (or re-pasted) is never re-parsed
  - Provider presets: VISION_PROVIDER=openai|dashscope|zhipu|siliconflow|moonshot
  - Never blocks: any crash returns {}

Configuration: environment variables (see README). No code changes needed to
switch providers.

Usage in Claude Code settings.json:

    {
      "hooks": {
        "UserPromptSubmit": [{
          "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/hooks/image-vision.py",
            "timeout": 60,
            "statusMessage": "解析图片中..."
          }]
        }]
      }
    }

Standalone test:

    python3 image-vision.py --test-image /path/to/screenshot.png
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Configuration (override via env vars)
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".claude" / "image-cache"
PROCESSED_FILE = CACHE_DIR / ".vision-processed"
RECENT_WINDOW = int(os.environ.get("VISION_RECENT_WINDOW", "3600"))
TIMEOUT = int(os.environ.get("VISION_TIMEOUT", "45"))
MAX_TOKENS = int(os.environ.get("VISION_MAX_TOKENS", "1200"))

API_BASE = os.environ.get(
    "VISION_API_BASE", "https://api.openai.com/v1/chat/completions"
)
API_KEY = os.environ.get("VISION_API_KEY", "")
MODEL = os.environ.get("VISION_MODEL", "gpt-4o")
EXTRA_HEADERS_JSON = os.environ.get("VISION_EXTRA_HEADERS", "")  # JSON object string
MAX_WORKERS = int(os.environ.get("VISION_MAX_WORKERS", "4"))  # parallel image parsing

# Provider presets: set VISION_PROVIDER to one of these to fill in defaults.
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "API_BASE": "https://api.openai.com/v1/chat/completions",
        "MODEL": "gpt-4o",
    },
    "dashscope": {
        "API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "MODEL": "qwen-vl-max",
    },
    "zhipu": {
        "API_BASE": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "MODEL": "glm-4v-plus",
    },
    "siliconflow": {
        "API_BASE": "https://api.siliconflow.cn/v1/chat/completions",
        "MODEL": "Qwen/Qwen2-VL-72B-Instruct",
    },
    "moonshot": {
        "API_BASE": "https://api.moonshot.cn/v1/chat/completions",
        "MODEL": "moonshot-v1-8k-vision-preview",
    },
}

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

VISION_PROMPT = (
    "请详细解析这张图片。要求：\n"
    "1. 如果是截图（终端/编辑器/网页/聊天），完整提取所有可见文字，按原布局组织\n"
    "2. 如果是 UI 设计稿/图表/流程图，描述布局、元素、关键数据\n"
    "3. 如果是照片，描述场景、主体、显著细节\n"
    "4. 如果含代码，原样输出代码块\n"
    "直接给出解析结果，不要加'这张图片显示'之类的开场白。"
)


# ---------------------------------------------------------------------------
# Provider preset application
# ---------------------------------------------------------------------------

def apply_preset() -> None:
    """Apply VISION_PROVIDER preset if set, env vars still override."""
    provider = os.environ.get("VISION_PROVIDER", "").strip().lower()
    if not provider or provider not in PROVIDER_PRESETS:
        return
    preset = PROVIDER_PRESETS[provider]
    global API_BASE, MODEL
    if "VISION_API_BASE" not in os.environ:
        API_BASE = preset["API_BASE"]
    if "VISION_MODEL" not in os.environ:
        MODEL = preset["MODEL"]


apply_preset()


# ---------------------------------------------------------------------------
# Processed-image tracking
# ---------------------------------------------------------------------------

def file_content_hash(path: str) -> str:
    """SHA-256 of file content. Same image at different paths → same hash."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_processed() -> set[str]:
    """Load set of content hashes that have already been parsed."""
    if not PROCESSED_FILE.exists():
        return set()
    try:
        return set(PROCESSED_FILE.read_text(encoding="utf-8").splitlines())
    except OSError:
        return set()


def append_processed(hashes: Iterable[str]) -> None:
    """Record content hashes as processed."""
    try:
        PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PROCESSED_FILE.open("a", encoding="utf-8") as f:
            for h in hashes:
                f.write(h + "\n")
    except OSError:
        pass


def find_new_images(processed_hashes: set[str]) -> list[str]:
    """Find image files not yet processed (by content hash, not path)."""
    if not CACHE_DIR.exists():
        return []
    cutoff = time.time() - RECENT_WINDOW
    found: list[tuple[float, str]] = []
    for ext in MIME_BY_EXT:
        for p in CACHE_DIR.rglob(f"*{ext}"):
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            sp = str(p)
            # Deduplicate by content hash — same image at different paths
            # or re-pasted images won't be re-parsed.
            try:
                content_hash = file_content_hash(sp)
            except OSError:
                continue
            if content_hash in processed_hashes:
                continue
            found.append((st.st_mtime, sp))
    found.sort()
    return [sp for _, sp in found]


# ---------------------------------------------------------------------------
# Multimodal API call
# ---------------------------------------------------------------------------

def describe_image(path: str) -> str:
    ext = Path(path).suffix.lower()
    mime = MIME_BY_EXT.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    data_url = f"data:{mime};base64,{b64}"

    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    if EXTRA_HEADERS_JSON:
        try:
            extra = json.loads(EXTRA_HEADERS_JSON)
            headers.update(extra)
        except json.JSONDecodeError:
            sys.stderr.write(
                "image-vision: VISION_EXTRA_HEADERS is not valid JSON, ignored\n"
            )

    req = urllib.request.Request(
        API_BASE,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Hook entry point
# ---------------------------------------------------------------------------

def _parse_one_image(img_path: str) -> tuple[str, str, str]:
    """Parse a single image. Returns (content_hash, path, description)."""
    content_hash = file_content_hash(img_path)
    try:
        desc = describe_image(img_path)
    except Exception as e:
        desc = f"[vision parse failed: {e}]"
    return content_hash, img_path, desc


def run_hook() -> None:
    # Consume stdin (Claude Code passes hook input JSON) — we don't use it.
    try:
        json.loads(sys.stdin.read() or "{}")
    except Exception:
        pass

    try:
        processed_hashes = load_processed()
        images = find_new_images(processed_hashes)
    except Exception:
        print(json.dumps({}))
        return

    if not images:
        print(json.dumps({}))
        return

    # Deduplicate within this invocation — same content hash → parse once
    seen_hashes: set[str] = set()
    unique_images: list[str] = []
    for img in images:
        try:
            h = file_content_hash(img)
        except OSError:
            continue
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_images.append(img)

    # Parallel parsing — each unique image is an independent API call
    max_workers = min(len(unique_images), int(os.environ.get("VISION_MAX_WORKERS", "4")))
    results: list[tuple[str, str, str]] = []

    if len(unique_images) == 1:
        # Single image: no thread overhead
        results.append(_parse_one_image(unique_images[0]))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_parse_one_image, img): img for img in unique_images}
            for future in as_completed(futures):
                results.append(future.result())

    # Build output in original file order
    hash_to_result = {h: (p, d) for h, p, d in results}
    descriptions: list[str] = []
    newly_done: list[str] = []
    reported_hashes: set[str] = set()
    for img in images:
        h = file_content_hash(img)
        if h in hash_to_result and h not in reported_hashes:
            _, desc = hash_to_result[h]
            descriptions.append(f"[图片 {img}]\n{desc}")
            newly_done.append(h)
            reported_hashes.add(h)

    append_processed(newly_done)

    additional = "\n\n".join(descriptions)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "<image_vision>\n"
                "以下是对本次提交中附带图片的自动解析"
                f"（由 {MODEL} 生成），主力模型可据此理解图片内容：\n\n"
                f"{additional}\n"
                "</image_vision>"
            ),
        }
    }
    print(json.dumps(out, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Standalone test mode
# ---------------------------------------------------------------------------

def run_test(image_path: str) -> int:
    if not API_KEY:
        sys.stderr.write(
            "ERROR: VISION_API_KEY env var not set. "
            "Export it first, e.g. export VISION_API_KEY=sk-...\n"
        )
        return 2
    p = Path(image_path).expanduser()
    if not p.exists():
        sys.stderr.write(f"ERROR: image not found: {p}\n")
        return 2
    print(f"Config:")
    print(f"  API_BASE = {API_BASE}")
    print(f"  MODEL    = {MODEL}")
    print(f"  TIMEOUT  = {TIMEOUT}s")
    print(f"Image: {p}")
    print(f"---")
    try:
        desc = describe_image(str(p))
    except Exception as e:
        sys.stderr.write(f"FAILED: {e}\n")
        return 1
    print(desc)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claude Code vision hook — gives non-multimodal main models the ability to see images."
    )
    parser.add_argument(
        "--test-image",
        metavar="PATH",
        help="Standalone test mode: describe a single image and exit. "
        "Useful for verifying your API config without going through Claude Code.",
    )
    args = parser.parse_args()

    if args.test_image:
        return run_test(args.test_image)

    try:
        run_hook()
        return 0
    except Exception as e:
        # Never block the turn on a hook crash.
        sys.stderr.write(f"image-vision hook crashed: {e}\n")
        print(json.dumps({}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
