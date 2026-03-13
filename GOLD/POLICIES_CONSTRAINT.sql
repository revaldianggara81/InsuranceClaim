--------------------------------------------------------
--  Constraints for Table POLICIES
--------------------------------------------------------

ALTER TABLE policies MODIFY (holder_name NOT NULL ENABLE);
ALTER TABLE policies MODIFY (driver_id   NOT NULL ENABLE);
ALTER TABLE policies ADD CHECK (status IN ('Active','Lapsed','Canceled')) ENABLE;
ALTER TABLE policies ADD CHECK (coverage_liability    IN ('Y','N')) ENABLE;
ALTER TABLE policies ADD CHECK (coverage_collision    IN ('Y','N')) ENABLE;
ALTER TABLE policies ADD CHECK (coverage_comprehensive IN ('Y','N')) ENABLE;
ALTER TABLE policies ADD PRIMARY KEY (policy_id)
  USING INDEX TABLESPACE "USERS" ENABLE;
