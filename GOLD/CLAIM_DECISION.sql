--------------------------------------------------------
--  DDL for Table CLAIM_DECISION  (claims_gold)
--------------------------------------------------------

CREATE TABLE claim_decision (
  "claim_id"           VARCHAR2(64),
  "decision"           VARCHAR2(64),
  "fusion_text"        VARCHAR2(4000),
  "action"             VARCHAR2(64),
  "reasons_json"       VARCHAR2(4000),
  "evidence_refs_json" VARCHAR2(4000),
  "confidence"         NUMBER(5,2),
  "est_payout_usd"     NUMBER(12,2),
  "created_at"         TIMESTAMP(6),
  "created_by"         VARCHAR2(128),
  "updated_at"         TIMESTAMP(6),
  "updated_by"         VARCHAR2(128)
)
TABLESPACE "USERS";

-- Ensure updated_by column exists (for incremental deployments on existing tables)
DECLARE
  v_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM user_tab_columns
  WHERE table_name = 'CLAIM_DECISION' AND column_name = 'updated_by';
  IF v_count = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE claim_decision ADD ("updated_by" VARCHAR2(128))';
  END IF;
END;
/
