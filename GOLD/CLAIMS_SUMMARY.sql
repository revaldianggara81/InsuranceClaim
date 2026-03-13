--------------------------------------------------------
--  DDL for Table CLAIMS_SUMMARY  (claims_gold)
--------------------------------------------------------

CREATE TABLE claims_summary (
  claimid            VARCHAR2(64),
  channel            VARCHAR2(64),
  claimtype          VARCHAR2(64),
  processedby        VARCHAR2(64),
  processingtimemins NUMBER,
  straightthrough    VARCHAR2(16),
  airecommendation   VARCHAR2(4000),
  suspiciousalert    VARCHAR2(16),
  claimpayout        NUMBER,
  csat               NUMBER
)
TABLESPACE "USERS";
