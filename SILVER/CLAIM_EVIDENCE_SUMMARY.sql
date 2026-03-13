--------------------------------------------------------
--  DDL for Table CLAIM_EVIDENCE_SUMMARY  (claims_silver)
--------------------------------------------------------

CREATE TABLE claim_evidence_summary (
  summary_id   NUMBER,
  claim_id     VARCHAR2(64)    NOT NULL,
  inbox_id     VARCHAR2(64)    NOT NULL,
  modality     VARCHAR2(64)    NOT NULL,
  source_uri   VARCHAR2(1000)  NOT NULL,
  findings     VARCHAR2(4000)  NOT NULL,
  confidence   NUMBER(5,2),
  created_at   TIMESTAMP       DEFAULT SYSTIMESTAMP
)
TABLESPACE "USERS";
