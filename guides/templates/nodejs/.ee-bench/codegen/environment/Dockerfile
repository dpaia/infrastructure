# DPAIA base pattern: https://jetbrains.team/p/ai-assistant/repositories/aia-docker-images/files/dockerfiles/Dpai-Bench/
FROM debian:12.11

# Install Node.js 24
RUN apt-get update && apt-get install -y curl git python3 && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git /app
WORKDIR /app
RUN git checkout {{ instance.base_commit }}

# Install project dependencies (npm workspaces)
RUN npm ci

# Prepare testing enviroment (install project specific browsers, etc)
RUN npm run test:setup-environment

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
