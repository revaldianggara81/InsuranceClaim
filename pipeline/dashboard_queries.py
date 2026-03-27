"""
Dashboard Queries — DB access for Claim Dashboard and Manual Review pages.
"""
import os
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

log = logging.getLogger(__name__)


def _make_engine(user_env, pw_env, default_user, default_pw):
    host    = os.getenv("ORACLE_BRONZE_HOST",    "localhost")
    port    = os.getenv("ORACLE_BRONZE_PORT",    "1521")
    service = os.getenv("ORACLE_BRONZE_SERVICE", "FREEPDB1")
    user    = os.getenv(user_env,   default_user)
    pw      = os.getenv(pw_env,     default_pw)
    return create_engine(
        f"oracle+oracledb://{user}:{pw}@{host}:{port}/?service_name={service}"
    )


def load_all_decisions() -> pd.DataFrame:
    """Load all claim decisions from Gold, newest first."""
    engine = _make_engine("ORACLE_GOLD_USER", "ORACLE_GOLD_PASSWORD", "claims_gold", "claims_gold")
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT
                    "claim_id"           AS claim_id,
                    "decision"           AS decision,
                    "action"             AS action,
                    "est_payout_usd"     AS payout_myr,
                    "confidence"         AS confidence,
                    "created_at"         AS created_at,
                    decision_tag         AS decision_tag
                FROM claim_decision
                ORDER BY "created_at" DESC NULLS LAST
            """), conn)
        # Format for display
        if not df.empty:
            df["payout_myr"]  = df["payout_myr"].apply(lambda x: f"RM {float(x or 0):,.2f}")
            df["confidence"]  = df["confidence"].apply(lambda x: f"{float(x or 0):.0%}")
            df["created_at"]  = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
            df["decision_tag"] = df["decision_tag"].fillna("—")
        return df
    except Exception as e:
        log.error(f"[Dashboard] load_all_decisions failed: {e}")
        return pd.DataFrame()


def load_claim_details(claim_id: str) -> dict:
    """Load full claim details for the Manual Review page."""
    engine_gold   = _make_engine("ORACLE_GOLD_USER",   "ORACLE_GOLD_PASSWORD",   "claims_gold",   "claims_gold")
    engine_bronze = _make_engine("ORACLE_BRONZE_USER", "ORACLE_BRONZE_PASSWORD", "claims_bronze", "claims_bronze")
    engine_silver = _make_engine("ORACLE_SILVER_USER", "ORACLE_SILVER_PASSWORD", "claims_silver", "claims_silver")

    result = {
        "claim_id":      claim_id,
        "narrative":     "",
        "evidence_uris": {},
        "findings":      [],
        "decision_row":  {},
    }

    try:
        with engine_gold.connect() as conn:
            df = pd.read_sql(
                text('SELECT * FROM claim_decision WHERE "claim_id" = :cid'),
                conn, params={"cid": claim_id}
            )
        if not df.empty:
            row = df.iloc[0]
            reasons_raw = str(row.get("reasons_json") or "")
            if "||PDF_URL:" in reasons_raw:
                reasons_raw = reasons_raw.split("||PDF_URL:", 1)[0].strip()
            result["decision_row"] = {
                "decision":     str(row.get("decision")    or ""),
                "action":       str(row.get("action")      or ""),
                "fusion_text":  str(row.get("fusion_text") or ""),
                "reasons_json": reasons_raw,
                "confidence":   float(row.get("confidence")    or 0),
                "payout_myr":   float(row.get("est_payout_usd") or 0),
                "decision_tag": str(row.get("decision_tag") or ""),
            }
    except Exception as e:
        log.error(f"[Dashboard] Gold load failed: {e}")

    try:
        with engine_bronze.connect() as conn:
            df = pd.read_sql(
                text("SELECT narrative, video_uri_claimant, image_uri_claimant, image_uri_counterparty "
                     "FROM inbound_claims WHERE claim_id_ext = :cid ORDER BY created_at DESC FETCH FIRST 1 ROWS ONLY"),
                conn, params={"cid": claim_id}
            )
        if not df.empty:
            row = df.iloc[0]
            result["narrative"] = str(row.get("narrative") or "")
            result["evidence_uris"] = {
                "video": str(row.get("video_uri_claimant")       or ""),
                "img1":  str(row.get("image_uri_claimant")       or ""),
                "img2":  str(row.get("image_uri_counterparty")   or ""),
            }
    except Exception as e:
        log.error(f"[Dashboard] Bronze load failed: {e}")

    try:
        with engine_silver.connect() as conn:
            df = pd.read_sql(
                text("SELECT modality, source_uri, findings, confidence "
                     "FROM claim_evidence_summary WHERE claim_id = :cid ORDER BY created_at"),
                conn, params={"cid": claim_id}
            )
        result["findings"] = df.to_dict("records") if not df.empty else []
    except Exception as e:
        log.error(f"[Dashboard] Silver load failed: {e}")

    return result


def apply_manual_decision(claim_id: str, human_decision: str) -> bool:
    """
    Apply human override to claim_decision Gold table.
    human_decision: "APPROVE" or "REJECT"
    """
    action = "PAYOUT" if human_decision == "APPROVE" else "NOTIFY"
    tag    = "APPROVE_MANUAL" if human_decision == "APPROVE" else "REJECT_MANUAL"
    engine = _make_engine("ORACLE_GOLD_USER", "ORACLE_GOLD_PASSWORD", "claims_gold", "claims_gold")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE claim_decision SET
                    "decision"   = :decision,
                    "action"     = :action,
                    decision_tag = :tag,
                    "updated_at" = :ts,
                    "updated_by" = :by
                WHERE "claim_id" = :cid
            """), {
                "decision": human_decision,
                "action":   action,
                "tag":      tag,
                "ts":       datetime.utcnow(),
                "by":       "human_reviewer",
                "cid":      claim_id,
            })
        log.info(f"[Dashboard] Manual override: {claim_id} → {human_decision} ({tag})")
        return True
    except Exception as e:
        log.error(f"[Dashboard] apply_manual_decision failed: {e}")
        return False
