#!/usr/bin/env bash
set -euo pipefail

REPO="${GITHUB_REPO:-MadeinPh1la/stacklion-api}"

echo "Bootstrapping labels in $REPO"

create_label() {
  local name="$1"
  local color="$2"
  local desc="$3"

  if gh label list --repo "$REPO" --search "$name" --limit 1 | grep -q "^$name\b"; then
    echo "Label '$name' already exists, skipping"
  else
    echo "Creating label '$name'"
    gh label create "$name" --repo "$REPO" --color "$color" --description "$desc"
  fi
}

# Areas
create_label "area:edgar"         "0366d6" "EDGAR ingestion, normalization, DQ, XBRL"
create_label "area:architecture"  "5319e7" "Architecture, layering, cross-cutting concerns"
create_label "area:modeling"      "0e8a16" "Modeling warehouse, metrics, valuation"
create_label "area:mcp"           "d93f0b" "MCP modeling capabilities and wiring"
create_label "area:reliability"   "fbca04" "SLOs, scaling, rate limits, ops"
create_label "area:ai-modeling"   "f97316" "Embeddings, explanations, advanced AI modeling"

# Phases
create_label "phase:E9"  "c5def5" "E9 – Persistent Data Quality & Fact Store"
create_label "phase:E10" "c5def5" "E10 – XBRL Normalization Layer"
create_label "phase:E11" "c5def5" "E11 – Reconciliation Engine"
create_label "phase:E12" "c5def5" "E12 – Auditability & Provenance"
create_label "phase:E13" "c5def5" "E13 – Modeling Warehouse Layer"
create_label "phase:E14" "c5def5" "E14 – Professional Modeling APIs"
create_label "phase:E15" "c5def5" "E15 – MCP Modeling Capabilities"
create_label "phase:E16" "c5def5" "E16 – Reliability, SLOs, and Scaling"
create_label "phase:E17" "c5def5" "E17 – AI and Advanced Modeling Enhancements"

# Types
create_label "type:feature"     "0052cc" "New feature"
create_label "type:enhancement" "5319e7" "Enhancement to existing feature"
create_label "type:test"        "e11d21" "Testing and test infra"
create_label "type:chore"       "d4c5f9" "Chore / maintenance / refactor"
create_label "type:docs"        "fef2c0" "Documentation work"

echo "Done."
