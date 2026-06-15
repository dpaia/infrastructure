# You can set Node.js version in ../metadata.json node_version
FROM node:{{ instance.node_version }}

ENV DEBIAN_FRONTEND=noninteractive

# Install common packages
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# AIA Dockerfile's automation scripts will add a GitHub auth token by detecting
# `git remote add origin https://github.com/dpaia/`
# and replacing it with
# `git remote add origin https://x-access-token:${DPAIA_GITHUB_READ_TOKEN}@github.com/dpaia`
RUN git init && \
    git remote add origin https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git && \
    git fetch origin --depth 1 {{ instance.base_commit }} && \
    git reset --hard FETCH_HEAD

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true

# Final dockerfile is generated. Last script should run after user switch so these two will be removed in final
# dockerfile and inserted again in appropriate places.
RUN bash preinstall-under-root.sh

RUN bash install-non-root.sh