--------------------------------------------------------
--  Constraints for Table DRIVERS
--------------------------------------------------------

ALTER TABLE drivers MODIFY (full_name      NOT NULL ENABLE);
ALTER TABLE drivers MODIFY (license_number NOT NULL ENABLE);
ALTER TABLE drivers ADD PRIMARY KEY (driver_id)
  USING INDEX TABLESPACE "USERS" ENABLE;
