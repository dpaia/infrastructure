#!/usr/bin/env bash
set -euo pipefail

# This script is a hook for installing regular project deps as a non-root user.
# It will be run after all eval setup preparations,
# before running the tests, in the root of your repo.
