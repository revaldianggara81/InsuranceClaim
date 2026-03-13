--------------------------------------------------------
--  DDL for Table DRIVERS  (claims_gold)
--------------------------------------------------------

CREATE TABLE drivers (
  driver_id      VARCHAR2(32),
  full_name      VARCHAR2(128),
  dob            DATE,
  license_number VARCHAR2(32),
  phone          VARCHAR2(32),
  email          VARCHAR2(128),
  created_at     TIMESTAMP(6)  DEFAULT SYSTIMESTAMP
)
TABLESPACE "USERS";
