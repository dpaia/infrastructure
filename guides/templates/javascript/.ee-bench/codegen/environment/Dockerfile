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
RUN git init && \
    git remote add origin https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git && \
    git fetch origin --depth 1 {{ instance.base_commit }} && \
    git reset --hard FETCH_HEAD

# Install project dependencies (npm workspaces)
RUN npm ci

# Prepare testing enviroment (install project specific browsers, etc)
RUN npm run test:setup-environment

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
