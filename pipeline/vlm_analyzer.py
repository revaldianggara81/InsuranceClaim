"""
VLM Analyzer — Ollama API backend (production-ready)

ACCIDENT VALIDATION is enforced here:
  - Every evidence item is classified: VALID_ACCIDENT | NOT_ACCIDENT | UNCLEAR
  - NOT_ACCIDENT → confidence = 0.0, is_accident = False
  - The decision engine uses this to hard-REJECT invalid evidence
"""
import os
import re
import cv2
import base64
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL",  "http://localhost:11434/v1")
OLLAMA_VLM_MODEL = os.getenv("OLLAMA_VLM_MODEL", "llava:7b")

# Classification labels
VALID_ACCIDENT = "VALID_ACCIDENT"
NOT_ACCIDENT   = "NOT_ACCIDENT"
UNCLEAR        = "UNCLEAR"

# ── Singleton Client ──────────────────────────────────────────────────────────

_client: Optional[OpenAI] = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=300.0)
    return _client


# ── Prompts ───────────────────────────────────────────────────────────────────

IMAGE_PROMPT = """You are an insurance fraud detection analyst. Your primary duty is to verify that submitted evidence actually shows a vehicle accident.

STEP 1 — ACCIDENT VALIDATION (mandatory, no exceptions):
Examine this image carefully.
- If it shows a damaged vehicle from a road accident or collision: write "ACCIDENT DETECTED" on the first line.
- If it does NOT show a vehicle accident (food, person, landscape, interior, unrelated object): write "NO ACCIDENT DETECTED" on the first line, then skip to STEP 3.

STEP 2 — DAMAGE ANALYSIS (only if accident detected):
- Describe visible damage: which parts, severity (minor/moderate/severe).
- Identify impact side: front / rear / left / right / multiple.

STEP 3 — CLASSIFICATION (always required, these two lines must appear at the end):
==Classification== [VALID_ACCIDENT or NOT_ACCIDENT or UNCLEAR]
==Confidence Score== [NUMBER]%

Examples:
  Non-accident: "NO ACCIDENT DETECTED. Image shows a food dish, not a vehicle.\n==Classification== NOT_ACCIDENT\n==Confidence Score== 97%"
  Accident: "ACCIDENT DETECTED. Front bumper severely crumpled, hood deformed.\n==Classification== VALID_ACCIDENT\n==Confidence Score== 91%"
"""

VIDEO_PROMPT = """You are an insurance fraud detection analyst. Your primary duty is to verify that submitted video evidence actually shows a vehicle accident.

STEP 1 — ACCIDENT VALIDATION (mandatory, no exceptions):
Watch these frames carefully.
- If they show a real road accident or vehicle collision: write "ACCIDENT DETECTED" on the first line.
- If they do NOT (normal traffic, no collision, unrelated content): write "NO ACCIDENT DETECTED" on the first line, then skip to STEP 3.

STEP 2 — ACCIDENT ANALYSIS (only if accident detected):
- Vehicles involved and collision type.
- Damage visible per vehicle.
- Sequence of events.

STEP 3 — CLASSIFICATION (always required, these two lines must appear at the end):
==Classification== [VALID_ACCIDENT or NOT_ACCIDENT or UNCLEAR]
==Confidence Score== [NUMBER]%

Examples:
  Non-accident: "NO ACCIDENT DETECTED. Frames show normal city traffic with no collision.\n==Classification== NOT_ACCIDENT\n==Confidence Score== 94%"
  Accident: "ACCIDENT DETECTED. Rear-end collision at junction, white sedan and red SUV.\n==Classification== VALID_ACCIDENT\n==Confidence Score== 89%"
"""


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_classification(text: str) -> str:
    m = re.search(r"==\s*Classification\s*==\s*(VALID_ACCIDENT|NOT_ACCIDENT|UNCLEAR)", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    upper = text.upper()
    if "NO ACCIDENT DETECTED" in upper:
        return NOT_ACCIDENT
    if "ACCIDENT DETECTED" in upper:
        return VALID_ACCIDENT
    return UNCLEAR


def _parse_confidence(text: str) -> float:
    try:
        m = re.search(r"==\s*[Cc]onfidence\s+[Ss]core\s*==\s*(\d+)%", text)
        if m:
            return round(int(m.group(1)) / 100, 2)
        m = re.search(r"[Cc]onfidence\s+[Ss]core\s*[:=]\s*(\d+)%", text)
        if m:
            return round(int(m.group(1)) / 100, 2)
        m = re.search(r"\b(\d{2,3})%", text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                return round(val / 100, 2)
    except Exception:
        pass
    return 0.0


def _build_result(raw_text: str, modality: str) -> dict:
    classification = _parse_classification(raw_text)
    confidence     = _parse_confidence(raw_text)
    # NOT_ACCIDENT always gets 0 confidence so it cannot pass any threshold
    if classification == NOT_ACCIDENT:
        confidence = 0.0
    return {
        "is_accident":    classification == VALID_ACCIDENT,
        "classification": classification,
        "confidence":     confidence,
        "summary":        raw_text.strip(),
        "modality":       modality,
        "error":          None,
    }


def _error_result(modality: str, error: str) -> dict:
    return {
        "is_accident":    False,
        "classification": UNCLEAR,
        "confidence":     0.0,
        "summary":        f"[VLM Error] {error}",
        "modality":       modality,
        "error":          error,
    }


# ── Image Resize ──────────────────────────────────────────────────────────────

def _resize_image(image_bytes: bytes, max_width: int = 640) -> bytes:
    try:
        import numpy as np
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes
        h, w = img.shape[:2]
        if w <= max_width:
            return image_bytes
        scale   = max_width / w
        resized = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
        _, buf  = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes()
    except Exception:
        return image_bytes


# ── Video Frame Sampler ───────────────────────────────────────────────────────

def _sample_frames(video_bytes: bytes, max_frames: int = 6):
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        tmp.write(video_bytes)
        tmp.flush()
        tmp.close()
        cap = cv2.VideoCapture(tmp.name)
        if not cap.isOpened():
            return [], []
        fps     = cap.get(cv2.CAP_PROP_FPS) or 24.0
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        count   = min(max_frames, max(1, nframes))
        indices = (
            [int(round(i * (nframes - 1) / (count - 1))) for i in range(count)]
            if count > 1 else [0]
        )
        frames, stamps = [], []
        for idx in sorted(set(indices)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                frames.append(buf.tobytes())
                stamps.append(round(idx / fps, 2))
        cap.release()
        return frames, stamps
    finally:
        os.unlink(tmp.name)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Analyze image evidence.

    Returns:
        {is_accident, classification, confidence, summary, modality, error}
        classification: VALID_ACCIDENT | NOT_ACCIDENT | UNCLEAR
    """
    try:
        print(f"[VLM] Analyzing image ({len(image_bytes)//1024}KB) via {OLLAMA_VLM_MODEL}")
        resized = _resize_image(image_bytes)
        b64     = base64.b64encode(resized).decode("utf-8")
        resp = _get_client().chat.completions.create(
            model=OLLAMA_VLM_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text",      "text":      IMAGE_PROMPT},
            ]}],
            max_tokens=512,
            temperature=0.1,
        )
        raw    = resp.choices[0].message.content or ""
        result = _build_result(raw, "image")
        print(f"[VLM] Image → {result['classification']} (conf={result['confidence']:.0%})")
        return result
    except Exception as e:
        print(f"[VLM] Image error: {e}")
        return _error_result("image", str(e))


def analyze_video(video_bytes: bytes) -> dict:
    """
    Analyze video evidence using frame sampling (max 6 frames).

    Returns:
        {is_accident, classification, confidence, summary, modality, error}
    """
    try:
        print(f"[VLM] Analyzing video ({len(video_bytes)//1024}KB) via {OLLAMA_VLM_MODEL}")
        frames, stamps = _sample_frames(video_bytes, max_frames=6)
        if not frames:
            return _error_result("video", "No frames extracted from video.")

        content = []
        for frame_bytes, t in zip(frames, stamps):
            b64 = base64.b64encode(frame_bytes).decode("utf-8")
            content.append({"type": "text",      "text":      f"[Frame at t={t}s]"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        content.append({"type": "text", "text": VIDEO_PROMPT})

        resp = _get_client().chat.completions.create(
            model=OLLAMA_VLM_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
            temperature=0.1,
        )
        raw    = resp.choices[0].message.content or ""
        result = _build_result(raw, "video")
        print(f"[VLM] Video → {result['classification']} (conf={result['confidence']:.0%})")
        return result
    except Exception as e:
        print(f"[VLM] Video error: {e}")
        return _error_result("video", str(e))


def analyze_images_parallel(items: list) -> list:
    """
    Analyze multiple images in parallel.
    items: list of (image_bytes, mime_type, label)
    Returns: list of (label, result_dict)
    """
    results = []
    with ThreadPoolExecutor(max_workers=min(len(items), 3)) as pool:
        futures = {
            pool.submit(analyze_image, img_bytes, mime): label
            for img_bytes, mime, label in items
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                results.append((label, future.result()))
            except Exception as e:
                results.append((label, _error_result("image", str(e))))
    return results
