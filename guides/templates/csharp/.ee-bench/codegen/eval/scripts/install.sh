#!/usr/bin/env bash
set -euo pipefail
dotnet restore
dotnet build --no-restore
