"""
Silver → Gold Enrichment Pipeline

Decision flow (deterministic, no LLM):
  R0  any evidence NOT_ACCIDENT    → REJECT / NOTIFY   (hard rule, bypasses all)
  R1  policy not active            → REJECT / ARCHIVE
  R2  duplicate claim              → MANUAL_REVIEW / ESCALATE
  R3  all confidence < 0.70        → MANUAL_REVIEW / NOTIFY
  R4  video + confidence >= 0.85   → APPROVE_FAST_TRACK / PAYOUT
  R5  image + confidence >= 0.80   → APPROVE / PAYOUT
  R6  default                      → MANUAL_REVIEW / NOTIFY

LLM role: generate fusion_text + reasons_json (explanation only, not decision).
"""
import os
import re
import json
import hashlib
import argparse
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict

import pandas as pd
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

USD_TO_MYR = Decimal("4.70")


# ── Schema Migration ──────────────────────────────────────────────────────────

def _ensure_schema(engine_gold):
    """Add decision_tag column if it doesn't exist (safe for existing DBs)."""
    try:
        with engine_gold.begin() as conn:
            conn.execute(text("ALTER TABLE claim_decision ADD (decision_tag VARCHAR2(50))"))
        print("[Gold] Added column: decision_tag")
    except Exception:
        pass  # ORA-01430: column already exists — that's fine


def _decision_tag(decision: str) -> str:
    if "APPROVE" in decision:
        return "APPROVE_SYSTEM"
    if decision == "REJECT":
        return "REJECT_SYSTEM"
    return "PENDING_REVIEW"


# ── DB Engines ────────────────────────────────────────────────────────────────

def make_engine(user_env: str, pw_env: str, default_user: str, default_pw: str):
    host    = os.getenv("ORACLE_BRONZE_HOST",    "localhost")
    port    = os.getenv("ORACLE_BRONZE_PORT",    "1521")
    service = os.getenv("ORACLE_BRONZE_SERVICE", "FREEPDB1")
    user    = os.getenv(user_env,   default_user)
    pw      = os.getenv(pw_env,     default_pw)
    return create_engine(
        f"oracle+oracledb://{user}:{pw}@{host}:{port}/?service_name={service}"
    )


# ── Python Rule Engine ────────────────────────────────────────────────────────

def _safe_decimal(val, default="0.0") -> Decimal:
    try:
        return Decimal(str(val)) if val is not None else Decimal(default)
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _apply_rules(
    policy_status: str,
    existing_claim: bool,
    confidences: list,
    modalities: list,
    has_non_accident: bool,
    limit_usd,
) -> tuple:
    """
    Deterministic rule engine.
    Returns (decision, action, est_payout_myr: Decimal)
    """
    max_conf  = max(confidences, default=0.0)
    limit_myr = _safe_decimal(limit_usd) * USD_TO_MYR

    # R0: Hard reject — evidence is not a car accident
    if has_non_accident:
        return "REJECT", "NOTIFY", Decimal("0.0")

    # R1: Policy not active
    if str(policy_status or "").strip().lower() != "active":
        return "REJECT", "ARCHIVE", Decimal("0.0")

    # R2: Duplicate claim
    if existing_claim:
        return "MANUAL_REVIEW", "ESCALATE", Decimal("0.0")

    # R3: All evidence low confidence
    if max_conf < 0.70:
        return "MANUAL_REVIEW", "NOTIFY", Decimal("0.0")

    # R4: Video + high confidence → fast track
    if "video" in modalities and max_conf >= 0.85:
        payout = (limit_myr * Decimal("0.80") * _safe_decimal(max_conf)).quantize(Decimal("0.01"))
        return "APPROVE_FAST_TRACK", "PAYOUT", payout

    # R5: Image + good confidence
    if "image" in modalities and max_conf >= 0.80:
        payout = (limit_myr * Decimal("0.60") * _safe_decimal(max_conf)).quantize(Decimal("0.01"))
        return "APPROVE", "PAYOUT", payout

    # R6: Default
    return "MANUAL_REVIEW", "NOTIFY", Decimal("0.0")


# ── LLM — Narrative Only ──────────────────────────────────────────────────────

NARRATIVE_PROMPT = """You are a senior insurance claims adjuster writing a professional claim assessment report.

Given the claim data below, generate exactly two fields:

1. fusion_text — A professional narrative paragraph (4-6 sentences):
   - Sentence 1: Describe the incident (when, where, vehicles involved, collision type).
   - Sentence 2: Describe what each piece of evidence shows (specific damage, affected parts, severity).
   - Sentence 3: State which policy section and coverage applies, referencing the page number.
   - Sentence 4: Explain what triggered this decision (rule applied, confidence level, risk assessment).
   - Sentence 5: State the recommended next step for the adjuster (payout, workshop referral, or escalation).

2. reasons_json — A structured string of 4-5 descriptive sentences, each explaining one reason for the decision, with policy page references in [Page N] format. Each sentence must be complete and informative, not just a label.
   Example format: "Policy confirmed active and in force at date of incident (Page 2). Video footage at 91% confidence clearly shows a rear-end collision consistent with the claimant's account, meeting the fast-track threshold under Section 4.1 (Page 7). Own damage to claimant vehicle is covered under Section 3 — Collision Coverage (Page 7), with an estimated repair value within policy limits. Third-party liability applies under Section 5 (Page 12) as damage to the counterparty vehicle is documented. Payout is recommended based on evidence strength and policy coverage confirmed."

Return ONLY valid JSON with exactly these two keys (no markdown, no extra text outside the JSON):
{"fusion_text": "...", "reasons_json": "..."}

Strict rules:
- Single-line strings only — no newlines inside values
- Double quotes for all keys and string values
- Do NOT mention the decision name or payout amount in reasons_json

Claim data:
"""

_SINGLETON_LLM = None

def _get_llm_client():
    global _SINGLETON_LLM
    if _SINGLETON_LLM is None:
        from openai import OpenAI
        _SINGLETON_LLM = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
            timeout=300.0,
        )
    return _SINGLETON_LLM


def _llm_call(prompt: str) -> str:
    model = os.getenv("OLLAMA_TEXT_MODEL", "qwen2:7b")
    resp  = _get_llm_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=768,
        temperature=0.3,
    )
    return resp.choices[0].message.content if resp.choices else ""


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        raw = m.group()
        try:
            return json.loads(raw)
        except Exception:
            pass
        try:
            fixed = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', raw)
            fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)
            return json.loads(fixed)
        except Exception:
            pass
    return {}


def _generate_narrative(claim_id, decision, action, payout_myr, rows, kb_content, pdf_url) -> tuple:
    """Call LLM to generate fusion_text and reasons_json only. Decision is already determined."""
    modalities          = [r.modality for r in rows]
    confidences         = [float(r.confidence) for r in rows]
    narrative           = rows[0].narrative           or "No narrative provided."
    aggregated_findings = rows[0].aggregated_findings or "No findings."
    driver_name         = rows[0].full_name           or "Unknown"
    vehicle_make        = rows[0].vehicle_make        or "Unknown"
    vehicle_model       = rows[0].vehicle_model       or "Unknown"
    vehicle_year        = rows[0].vehicle_year        or "Unknown"

    kb_section = (
        f"\nPolicy Document (cite [Page N] when referencing):\n{kb_content[:5000]}\n"
    ) if kb_content else ""

    prompt = (
        f"{NARRATIVE_PROMPT}"
        f"Claim ID     : {claim_id}\n"
        f"Decision     : {decision} / {action}\n"
        f"Payout       : MYR {payout_myr}\n"
        f"Modalities   : {modalities}\n"
        f"Confidences  : {[f'{c:.0%}' for c in confidences]}\n"
        f"Driver       : {driver_name}\n"
        f"Vehicle      : {vehicle_year} {vehicle_make} {vehicle_model}\n"
        f"Narrative    : {narrative}\n"
        f"{kb_section}"
        f"Evidence Summary:\n{aggregated_findings}\n"
    )

    try:
        raw    = _llm_call(prompt)
        parsed = _extract_json(raw)
        fusion  = str(parsed.get("fusion_text", "")).strip().strip('"').strip("'")
        reasons = str(parsed.get("reasons_json", "")).strip().strip('"').strip("'")
    except Exception as e:
        print(f"[LLM] Narrative generation failed for {claim_id}: {e}")
        fusion  = ""
        reasons = ""

    # Fallback if LLM returns nothing useful
    if not fusion:
        max_conf = max(confidences, default=0.0)
        fusion = (
            f"Claim {claim_id} has been assessed. "
            f"Evidence reviewed: {', '.join(set(modalities))} at {max_conf:.0%} confidence. "
            f"Decision: {decision}. "
            f"{'Payout of MYR ' + str(payout_myr) + ' to be processed.' if 'APPROVE' in decision else 'No payout applicable.'}"
        )
    if not reasons:
        reasons = f"Decision based on policy review and evidence analysis. See policy document for coverage details."

    # Append PDF URL for UI hyperlink rendering
    if pdf_url:
        reasons = f"{reasons}||PDF_URL:{pdf_url}"

    return fusion, reasons


# ── Load Data (parameterized — no SQL injection) ──────────────────────────────

def load_data(engine_bronze, engine_silver, engine_gold, claim_id_filter=None):
    with engine_silver.connect() as conn:
        if claim_id_filter:
            df_silver = pd.read_sql(
                text("SELECT * FROM claim_evidence_summary WHERE claim_id = :cid"),
                conn, params={"cid": claim_id_filter}
            )
        else:
            df_silver = pd.read_sql("SELECT * FROM claim_evidence_summary", conn)

    with engine_gold.connect() as conn:
        df_policy = pd.read_sql("SELECT * FROM policies", conn)
        # Check existing decisions (not the empty `claims` reference table)
        df_claims = pd.read_sql('SELECT "claim_id" AS claim_id FROM claim_decision', conn)
        df_driver = pd.read_sql("SELECT * FROM drivers", conn)

    with engine_bronze.connect() as conn:
        df_inbox = pd.read_sql(
            "SELECT claim_id_ext, policy_id, narrative FROM inbound_claims", conn
        )

    df_findings = (
        df_silver.groupby("claim_id")["findings"]
        .apply(lambda x: "\n".join(x))
        .reset_index()
        .rename(columns={"findings": "aggregated_findings"})
    )

    df_joined = (
        df_silver
        .merge(df_inbox, left_on="claim_id", right_on="claim_id_ext", how="left")
        .merge(
            df_policy[[
                "policy_id", "status", "limit_property_usd",
                "driver_id", "vehicle_make", "vehicle_model", "vehicle_year",
            ]],
            on="policy_id", how="left",
        )
        .merge(df_driver[["driver_id", "full_name", "license_number"]], on="driver_id", how="left")
        .merge(
            df_claims.rename(columns={"claim_id": "existing_claim_id"}),
            left_on="claim_id", right_on="existing_claim_id", how="left",
        )
        .merge(df_findings, on="claim_id", how="left")
    )

    return df_joined


# ── Per-Claim Processing ──────────────────────────────────────────────────────

def process_claim(claim_id, rows, kb_content: str = "", pdf_url: str = "") -> tuple:
    """
    Apply rule engine → generate narrative → return result tuple.
    Decision is ALWAYS made by rules, never by LLM.
    """
    modalities   = [r.modality          for r in rows]
    confidences  = [float(r.confidence) for r in rows]
    uris         = [r.source_uri        for r in rows]
    policy_status   = rows[0].status
    existing_claim  = bool(pd.notna(rows[0].existing_claim_id) and rows[0].existing_claim_id)
    limit_usd       = rows[0].limit_property_usd

    # R0 check: any finding tagged as NOT_ACCIDENT
    has_non_accident = any(
        str(r.findings or "").startswith("[NOT_ACCIDENT]")
        for r in rows
    )

    # ── Deterministic Decision ────────────────────────────────────────────────
    decision, action, payout_myr = _apply_rules(
        policy_status, existing_claim, confidences, modalities,
        has_non_accident, limit_usd,
    )
    print(f"[Rules] {claim_id} → {decision} / {action} / MYR {payout_myr}")

    # ── LLM generates narrative only ──────────────────────────────────────────
    fusion, reasons = _generate_narrative(
        claim_id, decision, action, payout_myr, rows, kb_content, pdf_url
    )

    tag = _decision_tag(decision)

    return (
        claim_id,
        decision,
        fusion,
        action,
        reasons,
        json.dumps(uris),
        _safe_decimal(max(confidences)),
        payout_myr,
        tag,
        datetime.utcnow(), "system",
        datetime.utcnow(), "system",
    )


# ── Write to Gold ──────────────────────────────────────────────────────────────

def upsert_gold(engine_gold, df_out):
    merge_sql = text("""
        MERGE INTO claim_decision t
        USING (SELECT :claim_id AS claim_id FROM dual) s
        ON (t."claim_id" = s.claim_id)
        WHEN MATCHED THEN UPDATE SET
            t."decision"           = :decision,
            t."fusion_text"        = :fusion_text,
            t."action"             = :action,
            t."reasons_json"       = :reasons_json,
            t."evidence_refs_json" = :evidence_refs_json,
            t."confidence"         = :confidence,
            t."est_payout_usd"     = :est_payout_usd,
            t.decision_tag         = :decision_tag,
            t."updated_at"         = :updated_at,
            t."updated_by"         = :updated_by
        WHEN NOT MATCHED THEN INSERT (
            "claim_id", "decision", "fusion_text", "action",
            "reasons_json", "evidence_refs_json", "confidence", "est_payout_usd",
            decision_tag, "created_at", "created_by", "updated_at", "updated_by"
        ) VALUES (
            :claim_id, :decision, :fusion_text, :action,
            :reasons_json, :evidence_refs_json, :confidence, :est_payout_usd,
            :decision_tag, :created_at, :created_by, :updated_at, :updated_by
        )
    """)
    with engine_gold.connect() as conn:
        for _, row in df_out.iterrows():
            conn.execute(merge_sql, {
                "claim_id":           row["claim_id"],
                "decision":           row["decision"],
                "fusion_text":        row["fusion_text"],
                "action":             row["action"],
                "reasons_json":       row["reasons_json"],
                "evidence_refs_json": row["evidence_refs_json"],
                "confidence":         float(row["confidence"])      if row["confidence"]      is not None else None,
                "est_payout_usd":     float(row["est_payout_usd"])  if row["est_payout_usd"]  is not None else None,
                "decision_tag":       row["decision_tag"],
                "created_at":         row["created_at"],
                "created_by":         row["created_by"],
                "updated_at":         row["updated_at"],
                "updated_by":         row["updated_by"],
            })
        conn.commit()
    print(f"[Gold] Upserted {len(df_out)} record(s) to claim_decision")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(claim_id_filter=None):
    engine_bronze = make_engine("ORACLE_BRONZE_USER", "ORACLE_BRONZE_PASSWORD", "claims_bronze", "claims_bronze")
    engine_silver = make_engine("ORACLE_SILVER_USER", "ORACLE_SILVER_PASSWORD", "claims_silver", "claims_silver")
    engine_gold   = make_engine("ORACLE_GOLD_USER",   "ORACLE_GOLD_PASSWORD",   "claims_gold",   "claims_gold")

    _ensure_schema(engine_gold)

    kb_content, pdf_url = "", ""
    try:
        from pipeline.kb_loader import load_kb_content
        kb_content, pdf_url = load_kb_content()
        print(f"[KB] Loaded {len(kb_content)} chars")
    except Exception as e:
        print(f"[KB] Skipped: {e}")

    df = load_data(engine_bronze, engine_silver, engine_gold, claim_id_filter)
    print(f"[Gold] Processing {df['claim_id'].nunique()} claim(s), {len(df)} evidence rows")

    grouped = defaultdict(list)
    for _, row in df.iterrows():
        grouped[row.claim_id].append(row)

    records = [
        process_claim(cid, rows, kb_content=kb_content, pdf_url=pdf_url)
        for cid, rows in grouped.items()
    ]

    df_out = pd.DataFrame(records, columns=[
        "claim_id", "decision", "fusion_text", "action", "reasons_json",
        "evidence_refs_json", "confidence", "est_payout_usd",
        "decision_tag", "created_at", "created_by", "updated_at", "updated_by",
    ])

    print(df_out[["claim_id", "decision", "action", "confidence", "est_payout_usd", "decision_tag"]].to_string())
    upsert_gold(engine_gold, df_out)
    print("[Gold] Pipeline complete.")
    return df_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--claim", default=None)
    args = parser.parse_args()
    run(claim_id_filter=args.claim)
