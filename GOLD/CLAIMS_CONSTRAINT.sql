--------------------------------------------------------
--  Constraints for Table CLAIMS
--------------------------------------------------------

ALTER TABLE claims MODIFY (policy_id         NOT NULL ENABLE);
ALTER TABLE claims MODIFY (claimant_driver_id NOT NULL ENABLE);
ALTER TABLE claims MODIFY (incident_ts        NOT NULL ENABLE);
ALTER TABLE claims ADD CHECK (status IN ('RECEIVED','IN_REVIEW','APPROVED','REJECTED','PAID')) ENABLE;
ALTER TABLE claims ADD CHECK (fault_party IN ('CLAIMANT','COUNTERPARTY','UNKNOWN')) ENABLE;
ALTER TABLE claims ADD PRIMARY KEY (claim_id)
  USING INDEX TABLESPACE "USERS" ENABLE;
