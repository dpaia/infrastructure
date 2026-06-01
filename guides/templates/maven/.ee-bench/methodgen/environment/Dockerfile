FROM eclipse-temurin:{{ instance.jvm_version }}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --break-system-packages tree-sitter tree-sitter-java

WORKDIR {{ instance.project_root }}
RUN git init && \
    git remote add origin https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git && \
    git fetch origin --depth 1 {{ instance.base_commit }} && \
    git reset --hard FETCH_HEAD

# Make mvnw executable and pre-fetch dependencies
RUN chmod +x ./mvnw && \
    ./mvnw dependency:go-offline -q

LABEL ee-bench.type="methodgen"
LABEL ee-bench.version="1.0"
RUN rm -rf {{ instance.project_root }}/.ee-bench/ 2>/dev/null || true
