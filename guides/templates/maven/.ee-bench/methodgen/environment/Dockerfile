FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir tree-sitter tree-sitter-java

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git {{ instance.project_root }}
WORKDIR {{ instance.project_root }}
RUN git checkout {{ instance.base_commit }}

LABEL ee-bench.type="methodgen"
LABEL ee-bench.version="1.0"
RUN rm -rf {{ instance.project_root }}/.ee-bench/ 2>/dev/null || true
