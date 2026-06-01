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

WORKDIR {{ instance.project_root }}
RUN git init && \
    git remote add origin https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git && \
    git fetch origin --depth 1 {{ instance.base_commit }} && \
    git reset --hard FETCH_HEAD

# Make gradlew executable and pre-fetch dependencies
RUN chmod +x ./gradlew && \
    ./gradlew dependencies --no-daemon -q

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf {{ instance.project_root }}/.ee-bench/ 2>/dev/null || true
