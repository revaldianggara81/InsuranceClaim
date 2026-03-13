--------------------------------------------------------
--  DDL for Table CLAIMS  (claims_gold)
--------------------------------------------------------

CREATE TABLE claims (
  claim_id               VARCHAR2(32),
  policy_id              VARCHAR2(32),
  claimant_driver_id     VARCHAR2(32),
  incident_ts            TIMESTAMP(6),
  location               VARCHAR2(64),
  narrative              VARCHAR2(2000),
  status                 VARCHAR2(24)   DEFAULT 'RECEIVED',
  counterparty_policy_id VARCHAR2(32),
  fault_party            VARCHAR2(16)   DEFAULT 'UNKNOWN',
  est_payout_usd         NUMBER(12,2),
  created_at             TIMESTAMP(6)   DEFAULT SYSTIMESTAMP
)
TABLESPACE "USERS";
