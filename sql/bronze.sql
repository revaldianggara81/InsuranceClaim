PROMPT =========================
PROMPT RUNNING BRONZE LAYER
PROMPT =========================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE inbound_claims CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

CREATE TABLE inbound_claims (
    inbox_id                NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id_ext            VARCHAR2(64)    NOT NULL,
    policy_id               VARCHAR2(64)    NOT NULL,
    incident_ts             TIMESTAMP       NOT NULL,
    location_lat            VARCHAR2(32),
    location_lon            VARCHAR2(32),
    narrative               VARCHAR2(4000),
    video_uri_claimant      VARCHAR2(1000),
    image_uri_claimant      VARCHAR2(1000),
    image_uri_counterparty  VARCHAR2(1000),
    status                  VARCHAR2(32),
    created_at              TIMESTAMP
);
