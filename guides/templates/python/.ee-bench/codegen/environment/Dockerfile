FROM python:{{ instance.python_version }}-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git init && \
    git remote add origin https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git && \
    git fetch origin --depth 1 {{ instance.base_commit }} && \
    git reset --hard FETCH_HEAD

# Install project dependencies
# Use whichever applies to your project:
RUN pip install --no-cache-dir -e ".[dev,test]" 2>/dev/null || \
    pip install --no-cache-dir -e ".[test]" 2>/dev/null || \
    pip install --no-cache-dir -e . 2>/dev/null || true
RUN pip install --no-cache-dir -r requirements-dev.txt 2>/dev/null || \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# Ensure pytest is available
RUN pip install --no-cache-dir pytest

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
