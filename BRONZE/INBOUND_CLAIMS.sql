--------------------------------------------------------
--  DDL for Table INBOUND_CLAIMS  (claims_bronze)
--------------------------------------------------------

CREATE TABLE inbound_claims (
  inbox_id                NUMBER,
  claim_id_ext            VARCHAR2(64)   NOT NULL,
  policy_id               VARCHAR2(64)   NOT NULL,
  incident_ts             TIMESTAMP      NOT NULL,
  location_lat            VARCHAR2(32),
  location_lon            VARCHAR2(32),
  narrative               VARCHAR2(4000),
  video_uri_claimant      VARCHAR2(1000),
  image_uri_claimant      VARCHAR2(1000),
  image_uri_counterparty  VARCHAR2(1000),
  status                  VARCHAR2(32),
  created_at              TIMESTAMP      DEFAULT SYSTIMESTAMP
)
TABLESPACE "USERS";

--------------------------------------------------------
--  Data for Table INBOUND_CLAIMS
--------------------------------------------------------

INSERT INTO inbound_claims (
  inbox_id, claim_id_ext, policy_id, incident_ts,
  location_lat, location_lon, narrative,
  video_uri_claimant, image_uri_claimant, image_uri_counterparty,
  status, created_at
) VALUES (
  1,
  'MOB-CLM-003',
  'TX-INS-45678',
  TIMESTAMP '2026-09-17 14:32:00',
  '33.1523',
  '-96.8235',
  'Right-of-way at stop-controlled intersection; struck by red SUV from the right.',
  '/Volumes/claims_bronze/claims_db/evidence/claimant_video_evidence/CarCollision.mp4',
  '/Volumes/claims_bronze/claims_db/evidence/claimant_img_evidence/yellow_car.png',
  '/Volumes/claims_bronze/claims_db/evidence/counterparty_img_evidence/red_car.png',
  'RECEIVED',
  CURRENT_TIMESTAMP
);
