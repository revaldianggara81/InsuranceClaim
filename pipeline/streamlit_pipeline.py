"""
Streamlit Full Pipeline — Bronze → Silver → Gold

Orchestrates:
  1. Input validation (evidence required)
  2. Policy seed in Gold
  3. Bronze insert
  4. VLM analysis → Silver (images in parallel, video sequential)
  5. Silver → Gold (rule engine + LLM narrative)
  6. Query Gold → return decision dict

Safety gate: if ANY evidence is NOT a car accident → REJECT before DB write.
"""
import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from pipeline.vlm_analyzer import analyze_image, analyze_video, analyze_images_parallel, NOT_ACCIDENT

log = logging.getLogger(__name__)


# ── DB Engines ────────────────────────────────────────────────────────────────

def _make_engine(user_env, pw_env, default_user, default_pw):
    host    = os.getenv("ORACLE_BRONZE_HOST",    "localhost")
    port    = os.getenv("ORACLE_BRONZE_PORT",    "1521")
    service = os.getenv("ORACLE_BRONZE_SERVICE", "FREEPDB1")
    user    = os.getenv(user_env,    default_user)
    pw      = os.getenv(pw_env,      default_pw)
    return create_engine(
        f"oracle+oracledb://{user}:{pw}@{host}:{port}/?service_name={service}"
    )


# ── Step 0: Seed Policy ───────────────────────────────────────────────────────

def _ensure_driver(conn, policy_id: str, holder_name: str) -> str:
    driver_id = f"DRV-{policy_id[-8:]}"
    count = conn.execute(
        text("SELECT COUNT(*) FROM drivers WHERE driver_id = :did"),
        {"did": driver_id}
    ).scalar()
    if count == 0:
        conn.execute(text("""
            INSERT INTO drivers (driver_id, full_name, dob, license_number, created_at)
            VALUES (:did, :name, TO_DATE('1990-01-01','YYYY-MM-DD'), :lic, SYSTIMESTAMP)
        """), {"did": driver_id, "name": holder_name or "Unknown", "lic": f"LIC-{policy_id[-6:]}"})
        log.info(f"Driver {driver_id} inserted.")
    return driver_id


def _ensure_policy(engine_gold, policy_id: str, holder_name: str):
    with engine_gold.begin() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM policies WHERE policy_id = :pid"),
            {"pid": policy_id}
        ).scalar()
        if count == 0:
            driver_id = _ensure_driver(conn, policy_id, holder_name)
            conn.execute(text("""
                INSERT INTO policies (
                    policy_id, holder_name, driver_id, status,
                    effective_date, expiry_date,
                    coverage_liability, coverage_collision, coverage_comprehensive,
                    deductible_collision_usd, deductible_comprehensive_usd,
                    limit_property_usd, limit_bi_per_person_usd, limit_bi_per_accident_usd,
                    premium_annual_usd, created_at, updated_at
                ) VALUES (
                    :pid, :name, :did, 'Active',
                    SYSDATE, ADD_MONTHS(SYSDATE, 12),
                    'Y', 'Y', 'Y', 500, 250,
                    50000, 100000, 300000,
                    1200, SYSTIMESTAMP, SYSTIMESTAMP
                )
            """), {"pid": policy_id, "name": holder_name or "Unknown", "did": driver_id})
            log.info(f"Policy {policy_id} inserted.")
        else:
            log.info(f"Policy {policy_id} already exists.")


# ── Step 1: Bronze ────────────────────────────────────────────────────────────

def _insert_bronze(engine_bronze, claim_id, policy_id, narrative,
                   video_uri, img1_uri, img2_uri) -> int:
    check_sql = text(
        "SELECT inbox_id FROM inbound_claims WHERE claim_id_ext = :cid "
        "ORDER BY created_at DESC FETCH FIRST 1 ROWS ONLY"
    )
    with engine_bronze.begin() as conn:
        row = conn.execute(check_sql, {"cid": claim_id}).fetchone()
        if row:
            log.info(f"Bronze: claim {claim_id} already exists (inbox_id={row[0]})")
            return row[0]

        conn.execute(text("""
            INSERT INTO inbound_claims (
                claim_id_ext, policy_id, incident_ts, narrative,
                video_uri_claimant, image_uri_claimant, image_uri_counterparty,
                status, created_at
            ) VALUES (
                :cid, :pid, :ts, :narrative,
                :video_uri, :img1_uri, :img2_uri,
                'RECEIVED', SYSTIMESTAMP
            )
        """), {
            "cid":       claim_id,
            "pid":       policy_id,
            "ts":        datetime.utcnow(),
            "narrative": narrative or "",
            "video_uri": video_uri,
            "img1_uri":  img1_uri,
            "img2_uri":  img2_uri,
        })
        row = conn.execute(check_sql, {"cid": claim_id}).fetchone()
        inbox_id = row[0] if row else 1
        log.info(f"Bronze: inserted {claim_id} (inbox_id={inbox_id})")
        return inbox_id


# ── Step 2: VLM → Silver ──────────────────────────────────────────────────────

def _stable_summary_id(inbox_id, source_uri: str) -> int:
    """Stable hash using hashlib (not builtin hash() which varies per process)."""
    key = f"{inbox_id}|{source_uri}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % 2_147_483_648


def _upsert_silver(engine_silver, claim_id, inbox_id, modality, source_uri, vlm_result: dict):
    """Store VLM result in Silver. Findings are prefixed with classification tag."""
    classification = vlm_result.get("classification", "UNCLEAR")
    summary        = vlm_result.get("summary", "No findings.")
    confidence     = vlm_result.get("confidence", 0.0)

    # Prefix findings with classification so rule engine can detect NOT_ACCIDENT
    findings = f"[{classification}] {summary}"

    summary_id = _stable_summary_id(inbox_id, source_uri)
    sql = text("""
        MERGE INTO claim_evidence_summary t
        USING (
            SELECT :sid AS summary_id, :cid AS claim_id,
                   :iid AS inbox_id,   :mod AS modality,
                   :uri AS source_uri, :fin AS findings,
                   :con AS confidence, :ts  AS created_at
            FROM dual
        ) s
        ON (t.inbox_id = s.inbox_id AND t.source_uri = s.source_uri)
        WHEN MATCHED THEN UPDATE SET
            t.summary_id = s.summary_id, t.claim_id   = s.claim_id,
            t.modality   = s.modality,   t.findings   = s.findings,
            t.confidence = s.confidence, t.created_at = s.created_at
        WHEN NOT MATCHED THEN INSERT (
            summary_id, claim_id, inbox_id, modality, source_uri,
            findings, confidence, created_at
        ) VALUES (
            s.summary_id, s.claim_id, s.inbox_id, s.modality, s.source_uri,
            s.findings,   s.confidence, s.created_at
        )
    """)
    with engine_silver.begin() as conn:
        conn.execute(sql, {
            "sid": summary_id,
            "cid": str(claim_id),
            "iid": str(inbox_id),
            "mod": modality,
            "uri": source_uri or "",
            "fin": findings[:4000],
            "con": float(confidence),
            "ts":  datetime.utcnow(),
        })
    log.info(f"Silver: upserted {modality} for {claim_id} [{classification}] conf={confidence:.0%}")


def _run_vlm_and_silver(
    engine_silver, claim_id, inbox_id,
    video_bytes, video_uri,
    img1_bytes, img1_uri, img1_filename,
    img2_bytes, img2_uri, img2_filename,
) -> list:
    """
    Run VLM analysis and store in Silver.
    Returns list of VLM result dicts.

    Images are analyzed in parallel; video is sequential (larger payload).
    """
    vlm_results = []

    # Video (sequential — large payload)
    if video_bytes and video_uri:
        log.info("[Pipeline] VLM: analyzing video...")
        result = analyze_video(video_bytes)
        if result.get("error"):
            result["classification"] = "UNCLEAR"
            result["confidence"]     = 0.55
            result["summary"]        = "Video submitted. Manual review required."
        _upsert_silver(engine_silver, claim_id, inbox_id, "video", video_uri, result)
        vlm_results.append(result)

    # Images (parallel)
    image_tasks = []
    if img1_bytes and img1_uri:
        mime = "image/png" if (img1_filename or "").lower().endswith(".png") else "image/jpeg"
        image_tasks.append((img1_bytes, mime, "img1"))
    if img2_bytes and img2_uri:
        mime = "image/png" if (img2_filename or "").lower().endswith(".png") else "image/jpeg"
        image_tasks.append((img2_bytes, mime, "img2"))

    if image_tasks:
        log.info(f"[Pipeline] VLM: analyzing {len(image_tasks)} image(s) in parallel...")
        parallel_results = analyze_images_parallel(image_tasks)
        label_to_uri = {"img1": img1_uri, "img2": img2_uri}
        for label, result in parallel_results:
            uri = label_to_uri.get(label, "")
            if result.get("error"):
                result["classification"] = "UNCLEAR"
                result["confidence"]     = 0.55
                result["summary"]        = "Image submitted. Manual review required."
            _upsert_silver(engine_silver, claim_id, inbox_id, "image", uri, result)
            vlm_results.append(result)

    return vlm_results


# ── Step 3: Silver → Gold ─────────────────────────────────────────────────────

def _run_silver_to_gold(claim_id: str):
    from pipeline.silver_to_gold import run as sg_run
    sg_run(claim_id_filter=claim_id)


# ── Step 4: Query Gold ────────────────────────────────────────────────────────

def _query_gold_decision(engine_gold, claim_id: str) -> Optional[dict]:
    try:
        with engine_gold.connect() as conn:
            df = pd.read_sql(
                text('SELECT * FROM claim_decision WHERE "claim_id" = :cid'),
                conn, params={"cid": claim_id}
            )
        if df.empty:
            return None
        row = df.iloc[0]

        raw_reasons  = str(row.get("reasons_json",       "") or "").strip().strip('"').strip("'")
        raw_evidence = str(row.get("evidence_refs_json", "") or "")

        try:
            evidence_list = json.loads(raw_evidence) if raw_evidence else []
        except Exception:
            evidence_list = [raw_evidence] if raw_evidence else []

        # Split PDF URL metadata embedded in reasons_json
        pdf_url = ""
        if "||PDF_URL:" in raw_reasons:
            parts       = raw_reasons.split("||PDF_URL:", 1)
            raw_reasons = parts[0].strip()
            pdf_url     = parts[1].strip()

        return {
            "claim_id":       str(row.get("claim_id",    claim_id)),
            "decision":       str(row.get("decision",    "MANUAL_REVIEW")),
            "action":         str(row.get("action",      "NOTIFY")),
            "est_payout_myr": float(row.get("est_payout_usd") or 0.0),
            "fusion_text":    str(row.get("fusion_text", "")),
            "confidence":     float(row.get("confidence") or 0.0),
            "reasons_json":   raw_reasons,
            "evidence_list":  evidence_list,
            "pdf_url":        pdf_url,
        }
    except Exception as e:
        log.error(f"Gold query error: {e}")
        return None


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_full_pipeline(
    claim_id:        str,
    policy_id:       str,
    holder_name:     str,
    narrative:       str,
    evidence_prefix: str           = "Evidance",
    video_bytes:     Optional[bytes] = None,
    video_filename:  Optional[str]   = None,
    img1_bytes:      Optional[bytes] = None,
    img1_filename:   Optional[str]   = None,
    img2_bytes:      Optional[bytes] = None,
    img2_filename:   Optional[str]   = None,
) -> dict:
    """
    Run Bronze → Silver → Gold pipeline for one claim.

    Safety gate: NOT_ACCIDENT evidence → immediate REJECT (no DB write).
    Returns: decision dict with keys:
        claim_id, decision, action, est_payout_myr, fusion_text,
        confidence, reasons_json, evidence_list, pdf_url
    """
    # ── Input Validation ──────────────────────────────────────────────────────
    has_any_evidence = bool(video_bytes or img1_bytes or img2_bytes)
    if not has_any_evidence:
        return {
            "claim_id":       claim_id,
            "decision":       "REJECT",
            "action":         "NOTIFY",
            "est_payout_myr": 0.0,
            "fusion_text":    "Submission rejected: no evidence files were uploaded. Please attach at least one image or video.",
            "confidence":     0.0,
            "reasons_json":   "No evidence provided.",
            "evidence_list":  [],
            "pdf_url":        "",
        }

    try:
        engine_bronze = _make_engine("ORACLE_BRONZE_USER", "ORACLE_BRONZE_PASSWORD", "claims_bronze", "claims_bronze")
        engine_silver = _make_engine("ORACLE_SILVER_USER", "ORACLE_SILVER_PASSWORD", "claims_silver", "claims_silver")
        engine_gold   = _make_engine("ORACLE_GOLD_USER",   "ORACLE_GOLD_PASSWORD",   "claims_gold",   "claims_gold")

        evidence_prefix = os.getenv("OCI_EVIDENCE_PREFIX", evidence_prefix)

        video_uri = f"{evidence_prefix}/{claim_id}/claimant_video_evidence/{video_filename}" if video_bytes and video_filename else None
        img1_uri  = f"{evidence_prefix}/{claim_id}/claimant_img_evidence/{img1_filename}"   if img1_bytes  and img1_filename  else None
        img2_uri  = f"{evidence_prefix}/{claim_id}/counterparty_img_evidence/{img2_filename}" if img2_bytes and img2_filename else None

        # Step 0: Seed policy
        _ensure_policy(engine_gold, policy_id, holder_name)

        # Step 1: Bronze
        inbox_id = _insert_bronze(engine_bronze, claim_id, policy_id, narrative,
                                   video_uri, img1_uri, img2_uri)

        # Step 2: VLM Analysis → Silver
        vlm_results = _run_vlm_and_silver(
            engine_silver, claim_id, inbox_id,
            video_bytes, video_uri,
            img1_bytes, img1_uri, img1_filename,
            img2_bytes, img2_uri, img2_filename,
        )

        # ── Safety Gate: immediate REJECT if any evidence is NOT_ACCIDENT ─────
        non_accidents = [r for r in vlm_results if r.get("classification") == NOT_ACCIDENT]
        if non_accidents:
            labels = [r.get("modality", "evidence") for r in non_accidents]
            reason = (
                f"Evidence rejected: the submitted {', '.join(labels)} does not show a vehicle accident. "
                f"Insurance claims require valid accident evidence. If you believe this is an error, "
                f"please resubmit with correct evidence."
            )
            log.warning(f"[Safety Gate] {claim_id}: NOT_ACCIDENT detected in {labels} → REJECT")
            return {
                "claim_id":       claim_id,
                "decision":       "REJECT",
                "action":         "NOTIFY",
                "est_payout_myr": 0.0,
                "fusion_text":    reason,
                "confidence":     0.0,
                "reasons_json":   "Evidence validation failed: submitted files are not vehicle accident evidence.",
                "evidence_list":  [u for u in [video_uri, img1_uri, img2_uri] if u],
                "pdf_url":        "",
            }

        # Step 3: Silver → Gold (rule engine + LLM narrative)
        _run_silver_to_gold(claim_id)

        # Step 4: Query Gold
        decision = _query_gold_decision(engine_gold, claim_id)

        if not decision:
            return {
                "claim_id":       claim_id,
                "decision":       "MANUAL_REVIEW",
                "action":         "NOTIFY",
                "est_payout_myr": 0.0,
                "fusion_text":    "Pipeline completed but decision record not found. Please retry.",
                "confidence":     0.0,
                "reasons_json":   "",
                "evidence_list":  [],
                "pdf_url":        "",
            }

        return decision

    except Exception as e:
        log.exception(f"Pipeline failed for {claim_id}: {e}")
        return {
            "claim_id":       claim_id,
            "decision":       "MANUAL_REVIEW",
            "action":         "NOTIFY",
            "est_payout_myr": 0.0,
            "fusion_text":    f"Pipeline error: {type(e).__name__}: {str(e)[:300]}",
            "confidence":     0.0,
            "reasons_json":   "System error — please contact support.",
            "evidence_list":  [],
            "pdf_url":        "",
        }
