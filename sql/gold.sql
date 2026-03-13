PROMPT =========================
PROMPT RUNNING GOLD LAYER
PROMPT =========================

-- policies
@/opt/oracle/project/GOLD/POLICIES.sql
@/opt/oracle/project/GOLD/POLICIES_CONSTRAINT.sql
@/opt/oracle/project/GOLD/POLICIES_DATA_TABLE.sql
@/opt/oracle/project/GOLD/SYS_C0032755.sql
-- drivers
@/opt/oracle/project/GOLD/DRIVERS.sql
@/opt/oracle/project/GOLD/DRIVERS_CONSTRAINT.sql
@/opt/oracle/project/GOLD/DRIVERS_DATA_TABLE.sql
@/opt/oracle/project/GOLD/SYS_C0032736.sql

-- claims
@/opt/oracle/project/GOLD/CLAIMS.sql
@/opt/oracle/project/GOLD/CLAIMS_CONSTRAINT.sql
@/opt/oracle/project/GOLD/CLAIMS_DATA_TABLE.sql
@/opt/oracle/project/GOLD/SYS_C0032748.sql

-- summary
@/opt/oracle/project/GOLD/CLAIMS_SUMMARY.sql
@/opt/oracle/project/GOLD/CLAIMS_SUMMARY_DATA_TABLE.sql

-- decision
@/opt/oracle/project/GOLD/CLAIM_DECISION.sql
@/opt/oracle/project/GOLD/CLAIM_DECISION_DATA_TABLE.sql
