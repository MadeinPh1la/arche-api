#!/usr/bin/env bash
set -euo pipefail

export $(grep -v '^#' .env.tests | grep '=' | xargs)
