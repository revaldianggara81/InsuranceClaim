PROMPT =========================
PROMPT RUNNING SILVER LAYER
PROMPT =========================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE claim_evidence_summary CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

CREATE TABLE claim_evidence_summary (
    summary_id   NUMBER,
    claim_id     VARCHAR2(64)    NOT NULL,
    inbox_id     VARCHAR2(64)    NOT NULL,
    modality     VARCHAR2(64)    NOT NULL,
    source_uri   VARCHAR2(1000)  NOT NULL,
    findings     VARCHAR2(4000)  NOT NULL,
    confidence   NUMBER,
    created_at   TIMESTAMP
);
