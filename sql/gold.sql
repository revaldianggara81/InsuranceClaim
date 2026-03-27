PROMPT =========================
PROMPT RUNNING GOLD LAYER
PROMPT =========================

-- ── Drop existing tables ────────────────────────────────────────────────────
BEGIN EXECUTE IMMEDIATE 'DROP TABLE claim_decision CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE claims_summary CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE claims CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE policies CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE drivers CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- ── Drivers ─────────────────────────────────────────────────────────────────
CREATE TABLE drivers (
    driver_id       VARCHAR2(32)    NOT NULL PRIMARY KEY,
    full_name       VARCHAR2(128)   NOT NULL,
    dob             DATE,
    license_number  VARCHAR2(32)    NOT NULL,
    phone           VARCHAR2(32),
    email           VARCHAR2(128),
    created_at      TIMESTAMP
);

-- ── Policies ─────────────────────────────────────────────────────────────────
CREATE TABLE policies (
    policy_id                   VARCHAR2(32)    NOT NULL PRIMARY KEY,
    holder_name                 VARCHAR2(128)   NOT NULL,
    driver_id                   VARCHAR2(32)    NOT NULL,
    vehicle_year                NUMBER,
    vehicle_make                VARCHAR2(64),
    vehicle_model               VARCHAR2(64),
    vehicle_color               VARCHAR2(32),
    vin_last6                   VARCHAR2(6),
    status                      VARCHAR2(16),
    effective_date              DATE,
    expiry_date                 DATE,
    coverage_liability          CHAR(1),
    coverage_collision          CHAR(1),
    coverage_comprehensive      CHAR(1),
    deductible_collision_usd    NUMBER,
    deductible_comprehensive_usd NUMBER,
    limit_property_usd          NUMBER,
    limit_bi_per_person_usd     NUMBER,
    limit_bi_per_accident_usd   NUMBER,
    premium_annual_usd          NUMBER,
    created_at                  TIMESTAMP,
    updated_at                  TIMESTAMP,
    CONSTRAINT fk_policy_driver FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
);

-- ── Claims (historical reference) ────────────────────────────────────────────
CREATE TABLE claims (
    claim_id                VARCHAR2(32)    NOT NULL PRIMARY KEY,
    policy_id               VARCHAR2(32)    NOT NULL,
    claimant_driver_id      VARCHAR2(32)    NOT NULL,
    incident_ts             TIMESTAMP       NOT NULL,
    location                VARCHAR2(64),
    narrative               VARCHAR2(2000),
    status                  VARCHAR2(24),
    counterparty_policy_id  VARCHAR2(32),
    fault_party             VARCHAR2(16),
    est_payout_usd          NUMBER,
    created_at              TIMESTAMP,
    CONSTRAINT fk_claim_policy FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);

-- ── Claims Summary ───────────────────────────────────────────────────────────
CREATE TABLE claims_summary (
    summary_id  NUMBER PRIMARY KEY,
    claim_id    VARCHAR2(32),
    total_paid  NUMBER,
    created_at  TIMESTAMP
);

-- ── Claim Decision (AI output) ────────────────────────────────────────────────
CREATE TABLE claim_decision (
    "claim_id"           VARCHAR2(64),
    "decision"           VARCHAR2(64),
    "fusion_text"        VARCHAR2(4000),
    "action"             VARCHAR2(64),
    "reasons_json"       VARCHAR2(4000),
    "evidence_refs_json" VARCHAR2(4000),
    "confidence"         NUMBER,
    "est_payout_usd"     NUMBER,
    "created_at"         TIMESTAMP,
    "created_by"         VARCHAR2(128),
    "updated_at"         TIMESTAMP,
    "updated_by"         VARCHAR2(128),
    decision_tag         VARCHAR2(50)
);
