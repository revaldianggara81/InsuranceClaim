--------------------------------------------------------
--  DDL for Table POLICIES  (claims_gold)
--------------------------------------------------------

CREATE TABLE policies (
  policy_id                    VARCHAR2(32),
  holder_name                  VARCHAR2(128),
  driver_id                    VARCHAR2(32),
  vehicle_year                 NUMBER(4,0),
  vehicle_make                 VARCHAR2(64),
  vehicle_model                VARCHAR2(64),
  vehicle_color                VARCHAR2(32),
  vin_last6                    VARCHAR2(6),
  status                       VARCHAR2(16)   DEFAULT 'Active',
  effective_date               DATE,
  expiry_date                  DATE,
  coverage_liability           CHAR(1)        DEFAULT 'Y',
  coverage_collision           CHAR(1)        DEFAULT 'Y',
  coverage_comprehensive       CHAR(1)        DEFAULT 'N',
  deductible_collision_usd     NUMBER(10,2),
  deductible_comprehensive_usd NUMBER(10,2),
  limit_property_usd           NUMBER(12,2),
  limit_bi_per_person_usd      NUMBER(12,2),
  limit_bi_per_accident_usd    NUMBER(12,2),
  premium_annual_usd           NUMBER(10,2),
  created_at                   TIMESTAMP(6)   DEFAULT SYSTIMESTAMP,
  updated_at                   TIMESTAMP(6)
)
TABLESPACE "USERS";
