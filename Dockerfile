FROM container-registry.oracle.com/database/free:latest

USER root

# copy seluruh project
COPY . /opt/oracle/project

# permission
RUN chown -R oracle:oinstall /opt/oracle/project

USER oracle

CMD /bin/bash -c "\
/opt/oracle/runOracle.sh & \
echo 'Waiting for Oracle Listener...' && \
until lsnrctl status > /dev/null 2>&1; do \
  sleep 5; \
done && \
echo 'Listener is ready.' && \
sleep 40 && \
echo 'Running SQL pipeline...' && \
sqlplus -s 'sys/Osc-indonesia123!@FREEPDB1 as sysdba' @/opt/oracle/project/init.sql && \
echo 'Pipeline finished.' && \
wait"