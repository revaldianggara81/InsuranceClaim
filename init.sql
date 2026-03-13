WHENEVER SQLERROR CONTINUE
SET ECHO ON
ALTER SESSION SET CONTAINER = FREEPDB1;

PROMPT Creating schemas...

@/opt/oracle/project/create_user.sql

PROMPT Running Bronze Layer...
CONNECT claims_bronze/claims_bronze@FREEPDB1
@/opt/oracle/project/sql/bronze.sql

PROMPT Running Silver Layer...
CONNECT claims_silver/claims_silver@FREEPDB1
@/opt/oracle/project/sql/silver.sql

PROMPT Running Gold Layer...
CONNECT claims_gold/claims_gold@FREEPDB1
@/opt/oracle/project/sql/gold.sql

PROMPT Pipeline Completed.

EXIT;
