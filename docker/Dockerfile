# Airflow image + an isolated virtualenv for the pipeline scripts.
# Mirrors the local setup: Airflow runs the scripts with PIPELINE_PYTHON (a separate
# interpreter), so pandas/psycopg2 never fight Airflow's own pinned dependencies.
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}
ARG AIRFLOW_VERSION=3.3.2

USER airflow

# 1) pipeline virtualenv (rebuild the image after changing requirements.txt)
COPY --chown=airflow:0 requirements.txt /tmp/pipeline-requirements.txt
RUN python -m venv /opt/airflow/pipeline-venv \
 && /opt/airflow/pipeline-venv/bin/pip install --no-cache-dir -r /tmp/pipeline-requirements.txt

# 2) Slack provider for failure alerts (pinning airflow keeps pip from upgrading it)
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" apache-airflow-providers-slack
