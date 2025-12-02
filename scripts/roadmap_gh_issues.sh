#!/usr/bin/env bash

set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-MadeinPh1la/stacklion-api}"
DEFAULT_ASSIGNEE="${DEFAULT_ASSIGNEE:-REPLACE_ME}"

# Usage:
#   export GITHUB_REPO="your/repo"
#   export DEFAULT_ASSIGNEE="your-github-username"
#   ./stacklion_all_phases_gh_issues.sh

echo "Using repo: $GITHUB_REPO"
echo "Default assignee: $DEFAULT_ASSIGNEE"
echo

echo "Creating issue E9-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-1: Implement EDGAR Fact Store Schema" \
  --body "## Summary
Define and migrate the initial persistent fact-level storage for normalized EDGAR statements.

This schema will store canonical financial facts (IS/BS/CF) at the granularity of:
- company (CIK)
- statement_type
- fiscal_year / fiscal_period
- statement_date
- metric
- version_sequence

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:feature" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-2: Fact Store Repository and Application Integration" \
  --body "## Summary
Implement repository and application-layer wiring that persists canonical normalized statements into the fact store.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:feature" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-3: Data Quality Rule Engine (Phase 1)" \
  --body "## Summary
Implement the first iteration of a Data Quality (DQ) rules engine over EDGAR facts.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:feature" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-4: DQ Ledger Schema (Quality & Anomaly Tables)" \
  --body "## Summary
Create persistent storage for DQ evaluations and anomalies.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:feature" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-5: Data Quality APIs for EDGAR Statements" \
  --body "## Summary
Expose EDGAR Data Quality information over HTTP so clients can inspect quality flags and anomalies.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:feature" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-6 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-6: Enhance EDGAR Ingestion Reliability (Retries & Circuit Breakers)" \
  --body "## Summary
Add bounded retries, exponential backoff, and circuit breaker behavior around EDGAR ingestion.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:enhancement" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-7 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-7: Add DQ Flags to EDGAR Fundamentals Responses" \
  --body "## Summary
Enrich existing EDGAR fundamentals / normalized statement responses with optional DQ metadata.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:enhancement" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-8 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-8: Architecture Tests for Fact Store and DQ Modules" \
  --body "## Summary
Extend architecture tests to cover new fact store and DQ modules and enforce layering rules.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:architecture,phase:E9,type:chore" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E9-9 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E9-9: End-to-End Tests for Fact Store + DQ Pipeline" \
  --body "## Summary
Add e2e tests for EDGAR ingestion → normalization → fact store → DQ evaluation → HTTP.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E9,type:test" \
  --milestone "E9 – Persistent Data Quality & Fact Store" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E10-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E10-1: XBRL Normalization Deliverable #1" \
  --body "## Summary
Deliverable #1 for E10 – XBRL Normalization Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E10,type:feature" \
  --milestone "E10 – XBRL Normalization Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E10-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E10-2: XBRL Normalization Deliverable #2" \
  --body "## Summary
Deliverable #2 for E10 – XBRL Normalization Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E10,type:feature" \
  --milestone "E10 – XBRL Normalization Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E10-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E10-3: XBRL Normalization Deliverable #3" \
  --body "## Summary
Deliverable #3 for E10 – XBRL Normalization Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E10,type:feature" \
  --milestone "E10 – XBRL Normalization Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E10-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E10-4: XBRL Normalization Deliverable #4" \
  --body "## Summary
Deliverable #4 for E10 – XBRL Normalization Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E10,type:enhancement" \
  --milestone "E10 – XBRL Normalization Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E10-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E10-5: XBRL Normalization Deliverable #5" \
  --body "## Summary
Deliverable #5 for E10 – XBRL Normalization Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E10,type:test" \
  --milestone "E10 – XBRL Normalization Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E11-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E11-1: Reconciliation Engine Deliverable #1" \
  --body "## Summary
Deliverable #1 for E11 – Reconciliation Engine, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E11,type:feature" \
  --milestone "E11 – Reconciliation Engine" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E11-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E11-2: Reconciliation Engine Deliverable #2" \
  --body "## Summary
Deliverable #2 for E11 – Reconciliation Engine, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E11,type:feature" \
  --milestone "E11 – Reconciliation Engine" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E11-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E11-3: Reconciliation Engine Deliverable #3" \
  --body "## Summary
Deliverable #3 for E11 – Reconciliation Engine, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E11,type:feature" \
  --milestone "E11 – Reconciliation Engine" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E11-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E11-4: Reconciliation Engine Deliverable #4" \
  --body "## Summary
Deliverable #4 for E11 – Reconciliation Engine, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E11,type:enhancement" \
  --milestone "E11 – Reconciliation Engine" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E11-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E11-5: Reconciliation Engine Deliverable #5" \
  --body "## Summary
Deliverable #5 for E11 – Reconciliation Engine, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E11,type:test" \
  --milestone "E11 – Reconciliation Engine" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E12-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E12-1: Provenance & Time-Travel Deliverable #1" \
  --body "## Summary
Deliverable #1 for E12 – Auditability & Provenance, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E12,type:feature" \
  --milestone "E12 – Auditability & Provenance" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E12-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E12-2: Provenance & Time-Travel Deliverable #2" \
  --body "## Summary
Deliverable #2 for E12 – Auditability & Provenance, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E12,type:feature" \
  --milestone "E12 – Auditability & Provenance" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E12-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E12-3: Provenance & Time-Travel Deliverable #3" \
  --body "## Summary
Deliverable #3 for E12 – Auditability & Provenance, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E12,type:feature" \
  --milestone "E12 – Auditability & Provenance" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E12-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E12-4: Provenance & Time-Travel Deliverable #4" \
  --body "## Summary
Deliverable #4 for E12 – Auditability & Provenance, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E12,type:enhancement" \
  --milestone "E12 – Auditability & Provenance" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E12-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E12-5: Provenance & Time-Travel Deliverable #5" \
  --body "## Summary
Deliverable #5 for E12 – Auditability & Provenance, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:edgar,phase:E12,type:test" \
  --milestone "E12 – Auditability & Provenance" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E13-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E13-1: Modeling Warehouse Deliverable #1" \
  --body "## Summary
Deliverable #1 for E13 – Modeling Warehouse Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E13,type:feature" \
  --milestone "E13 – Modeling Warehouse Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E13-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E13-2: Modeling Warehouse Deliverable #2" \
  --body "## Summary
Deliverable #2 for E13 – Modeling Warehouse Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E13,type:feature" \
  --milestone "E13 – Modeling Warehouse Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E13-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E13-3: Modeling Warehouse Deliverable #3" \
  --body "## Summary
Deliverable #3 for E13 – Modeling Warehouse Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E13,type:feature" \
  --milestone "E13 – Modeling Warehouse Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E13-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E13-4: Modeling Warehouse Deliverable #4" \
  --body "## Summary
Deliverable #4 for E13 – Modeling Warehouse Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E13,type:enhancement" \
  --milestone "E13 – Modeling Warehouse Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E13-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E13-5: Modeling Warehouse Deliverable #5" \
  --body "## Summary
Deliverable #5 for E13 – Modeling Warehouse Layer, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E13,type:test" \
  --milestone "E13 – Modeling Warehouse Layer" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E14-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E14-1: Modeling APIs Deliverable #1" \
  --body "## Summary
Deliverable #1 for E14 – Professional Modeling APIs, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E14,type:feature" \
  --milestone "E14 – Professional Modeling APIs" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E14-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E14-2: Modeling APIs Deliverable #2" \
  --body "## Summary
Deliverable #2 for E14 – Professional Modeling APIs, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E14,type:feature" \
  --milestone "E14 – Professional Modeling APIs" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E14-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E14-3: Modeling APIs Deliverable #3" \
  --body "## Summary
Deliverable #3 for E14 – Professional Modeling APIs, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E14,type:feature" \
  --milestone "E14 – Professional Modeling APIs" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E14-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E14-4: Modeling APIs Deliverable #4" \
  --body "## Summary
Deliverable #4 for E14 – Professional Modeling APIs, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E14,type:enhancement" \
  --milestone "E14 – Professional Modeling APIs" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E14-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E14-5: Modeling APIs Deliverable #5" \
  --body "## Summary
Deliverable #5 for E14 – Professional Modeling APIs, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:modeling,phase:E14,type:test" \
  --milestone "E14 – Professional Modeling APIs" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E15-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E15-1: MCP Modeling Deliverable #1" \
  --body "## Summary
Deliverable #1 for E15 – MCP Modeling Capabilities, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:mcp,phase:E15,type:feature" \
  --milestone "E15 – MCP Modeling Capabilities" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E15-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E15-2: MCP Modeling Deliverable #2" \
  --body "## Summary
Deliverable #2 for E15 – MCP Modeling Capabilities, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:mcp,phase:E15,type:feature" \
  --milestone "E15 – MCP Modeling Capabilities" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E15-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E15-3: MCP Modeling Deliverable #3" \
  --body "## Summary
Deliverable #3 for E15 – MCP Modeling Capabilities, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:mcp,phase:E15,type:feature" \
  --milestone "E15 – MCP Modeling Capabilities" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E15-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E15-4: MCP Modeling Deliverable #4" \
  --body "## Summary
Deliverable #4 for E15 – MCP Modeling Capabilities, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:mcp,phase:E15,type:enhancement" \
  --milestone "E15 – MCP Modeling Capabilities" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E15-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E15-5: MCP Modeling Deliverable #5" \
  --body "## Summary
Deliverable #5 for E15 – MCP Modeling Capabilities, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:mcp,phase:E15,type:test" \
  --milestone "E15 – MCP Modeling Capabilities" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E16-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E16-1: Reliability & SLO Deliverable #1" \
  --body "## Summary
Deliverable #1 for E16 – Reliability, SLOs, and Scaling, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:reliability,phase:E16,type:feature" \
  --milestone "E16 – Reliability, SLOs, and Scaling" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E16-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E16-2: Reliability & SLO Deliverable #2" \
  --body "## Summary
Deliverable #2 for E16 – Reliability, SLOs, and Scaling, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:reliability,phase:E16,type:feature" \
  --milestone "E16 – Reliability, SLOs, and Scaling" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E16-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E16-3: Reliability & SLO Deliverable #3" \
  --body "## Summary
Deliverable #3 for E16 – Reliability, SLOs, and Scaling, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:reliability,phase:E16,type:feature" \
  --milestone "E16 – Reliability, SLOs, and Scaling" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E16-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E16-4: Reliability & SLO Deliverable #4" \
  --body "## Summary
Deliverable #4 for E16 – Reliability, SLOs, and Scaling, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:reliability,phase:E16,type:enhancement" \
  --milestone "E16 – Reliability, SLOs, and Scaling" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E16-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E16-5: Reliability & SLO Deliverable #5" \
  --body "## Summary
Deliverable #5 for E16 – Reliability, SLOs, and Scaling, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:reliability,phase:E16,type:test" \
  --milestone "E16 – Reliability, SLOs, and Scaling" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E17-1 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E17-1: Advanced AI Modeling Deliverable #1" \
  --body "## Summary
Deliverable #1 for E17 – AI and Advanced Modeling Enhancements, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:ai-modeling,phase:E17,type:feature" \
  --milestone "E17 – AI and Advanced Modeling Enhancements" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E17-2 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E17-2: Advanced AI Modeling Deliverable #2" \
  --body "## Summary
Deliverable #2 for E17 – AI and Advanced Modeling Enhancements, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:ai-modeling,phase:E17,type:feature" \
  --milestone "E17 – AI and Advanced Modeling Enhancements" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E17-3 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E17-3: Advanced AI Modeling Deliverable #3" \
  --body "## Summary
Deliverable #3 for E17 – AI and Advanced Modeling Enhancements, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:ai-modeling,phase:E17,type:feature" \
  --milestone "E17 – AI and Advanced Modeling Enhancements" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E17-4 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E17-4: Advanced AI Modeling Deliverable #4" \
  --body "## Summary
Deliverable #4 for E17 – AI and Advanced Modeling Enhancements, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:ai-modeling,phase:E17,type:enhancement" \
  --milestone "E17 – AI and Advanced Modeling Enhancements" \
  --assignee "$DEFAULT_ASSIGNEE"

echo "Creating issue E17-5 in $GITHUB_REPO..."
gh issue create --repo "$GITHUB_REPO" \
  --title "E17-5: Advanced AI Modeling Deliverable #5" \
  --body "## Summary
Deliverable #5 for E17 – AI and Advanced Modeling Enhancements, see roadmap for full detail.

## Requirements
- See main roadmap/docs for detailed requirements.

## Acceptance Criteria
- Implementation meets roadmap acceptance criteria.
" \
  --label "area:ai-modeling,phase:E17,type:docs" \
  --milestone "E17 – AI and Advanced Modeling Enhancements" \
  --assignee "$DEFAULT_ASSIGNEE"

echo
echo "All issues created."
