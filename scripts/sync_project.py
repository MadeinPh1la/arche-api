#!/usr/bin/env python
"""
Project roadmap sync script (Kanban only).

Purpose:
    - Ensure the configured GitHub Project (Projects v2) exists.
    - For each phase (E9–E17), find issues by label (e.g. phase:E9).
    - Add those issues as items to the Project.
    - Set the Project "Status" field for each item based on labels / state.

Usage:
    GITHUB_TOKEN=<token> python scripts/sync_project.py .github/project-roadmap.yml

Requirements:
    - GITHUB_TOKEN must have:
        * repo
        * project
    - The Project must exist or will be created under the configured owner.
    - The Project must have a "Status" single-select field with options:
        * Backlog, In Progress, Blocked, Done
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import requests
import yaml

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"


# --------------------------------------------------------------------------- #
# Configuration data classes                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class PhaseConfig:
    """Per-phase configuration loaded from project-roadmap.yml."""

    code: str
    milestone: str
    label: str
    default_status: str


@dataclass
class ProjectConfig:
    """Project owner + identity configuration."""

    owner: str
    owner_type: str  # "USER" or "ORGANIZATION"
    name: str
    project_number: int | None


@dataclass
class StatusFieldConfig:
    """Configuration for the Project 'Status' single-select field."""

    name: str
    backlog: str
    in_progress: str
    blocked: str
    done: str


@dataclass
class ProjectFields:
    """Resolved Project field IDs / option IDs."""

    status_field_id: str | None
    status_option_ids: dict[str, str]


# --------------------------------------------------------------------------- #
# Config loading                                                              #
# --------------------------------------------------------------------------- #


def load_config(
    path: str,
) -> tuple[ProjectConfig, str, list[PhaseConfig], StatusFieldConfig | None, dict[str, Any]]:
    """Load roadmap configuration from YAML."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    project_cfg = cfg["project"]
    repo_cfg = cfg["repository"]
    phases_cfg = cfg["phases"]
    status_field_raw = cfg.get("status_field")
    status_mapping = cfg.get("status_mapping", {})

    project = ProjectConfig(
        owner=project_cfg["owner"],
        owner_type=project_cfg.get("owner_type", "USER"),
        name=project_cfg["name"],
        project_number=project_cfg.get("project_number"),
    )

    repo_full_name = repo_cfg["full_name"]

    phases: list[PhaseConfig] = []
    for p in phases_cfg:
        phases.append(
            PhaseConfig(
                code=p["code"],
                milestone=p["milestone"],
                label=p["label"],
                default_status=p.get("default_status", "Backlog"),
            )
        )

    status_cfg: StatusFieldConfig | None = None
    if status_field_raw is not None:
        states = status_field_raw.get("states", {})
        status_cfg = StatusFieldConfig(
            name=status_field_raw["name"],
            backlog=states.get("backlog", "Backlog"),
            in_progress=states.get("in_progress", "In Progress"),
            blocked=states.get("blocked", "Blocked"),
            done=states.get("done", "Done"),
        )

    return project, repo_full_name, phases, status_cfg, status_mapping


# --------------------------------------------------------------------------- #
# HTTP helpers                                                                #
# --------------------------------------------------------------------------- #


def github_headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(
        GITHUB_GRAPHQL,
        headers=github_headers(),
        json={"query": query, "variables": variables},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GraphQL error: {resp.status_code} {resp.text}")
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


def rest_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = requests.get(url, headers=github_headers(), params=params, timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"REST GET error {resp.status_code}: {resp.text}")
    return resp.json()


# --------------------------------------------------------------------------- #
# Project discovery / creation                                                #
# --------------------------------------------------------------------------- #


def find_or_create_project(config: ProjectConfig) -> tuple[str, int]:
    """Return (project_id, project_number) for Projects v2."""
    owner = config.owner

    # If project_number is pinned, fetch directly.
    if config.project_number is not None:
        query = """
        query($owner: String!, $number: Int!) {
          user(login: $owner) {
            projectV2(number: $number) {
              id
              number
              title
            }
          }
        }
        """
        data = graphql(query, {"owner": owner, "number": config.project_number})
        project = data["user"]["projectV2"]
        if project is None:
            raise RuntimeError(
                f"Project number {config.project_number} not found for {owner}"
            )
        return project["id"], project["number"]

    # Otherwise search by name and create if missing.
    if config.owner_type.upper() == "USER":
        query = """
        query($owner: String!) {
          user(login: $owner) {
            projectsV2(first: 50) {
              nodes {
                id
                number
                title
              }
            }
          }
        }
        """
        data = graphql(query, {"owner": owner})
        nodes = data["user"]["projectsV2"]["nodes"]
    else:
        query = """
        query($owner: String!) {
          organization(login: $owner) {
            projectsV2(first: 50) {
              nodes {
                id
                number
                title
              }
            }
          }
        }
        """
        data = graphql(query, {"owner": owner})
        nodes = data["organization"]["projectsV2"]["nodes"]

    for node in nodes:
        if node["title"] == config.name:
            return node["id"], node["number"]

    # Create new project.
    if config.owner_type.upper() == "USER":
        owner_query = """
        query($login: String!) {
          user(login: $login) { id }
        }
        """
        owner_data = graphql(owner_query, {"login": owner})
        owner_id = owner_data["user"]["id"]
    else:
        owner_query = """
        query($login: String!) {
          organization(login: $login) { id }
        }
        """
        owner_data = graphql(owner_query, {"login": owner})
        owner_id = owner_data["organization"]["id"]

    mutation = """
    mutation($ownerId: ID!, $title: String!) {
      createProjectV2(input: {ownerId: $ownerId, title: $title}) {
        projectV2 {
          id
          number
          title
        }
      }
    }
    """
    create_data = graphql(mutation, {"ownerId": owner_id, "title": config.name})
    proj = create_data["createProjectV2"]["projectV2"]
    return proj["id"], proj["number"]


# --------------------------------------------------------------------------- #
# Project fields: Status                                                      #
# --------------------------------------------------------------------------- #


def get_project_fields(
    project_id: str,
    status_cfg: StatusFieldConfig | None,
) -> ProjectFields:
    """Resolve field IDs and option IDs for Status field."""
    if status_cfg is None:
        return ProjectFields(status_field_id=None, status_option_ids={})

    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 50) {
            nodes {
              ... on ProjectV2SingleSelectField {
                __typename
                id
                name
                options {
                  id
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    data = graphql(query, {"projectId": project_id})
    nodes = data["node"]["fields"]["nodes"]

    status_field_id: str | None = None
    status_option_ids: dict[str, str] = {}

    for field in nodes:
        typename = field.get("__typename")
        if typename != "ProjectV2SingleSelectField":
            continue
        if field.get("name") != status_cfg.name:
            continue

        status_field_id = field["id"]
        for opt in field.get("options", []):
            raw_name = opt.get("name") or ""
            # Normalize: strip whitespace but preserve original case.
            name = raw_name.strip()
            if not name:
                continue
            status_option_ids[name] = opt["id"]
        break

    if status_field_id is None:
        raise RuntimeError(
            f"Project Status field '{status_cfg.name}' not found. "
            "Create it as a single-select field in the Project."
        )

    return ProjectFields(
        status_field_id=status_field_id,
        status_option_ids=status_option_ids,
    )

def set_status_for_item(
    project_id: str,
    item_id: str,
    fields: ProjectFields,
    status_value: str,
) -> None:
    """Set the Status field value for a project item."""
    if fields.status_field_id is None:
        return

    # First try exact match.
    option_id = fields.status_option_ids.get(status_value)

    # If that fails, try a case-insensitive match.
    if option_id is None:
        desired = status_value.strip().lower()
        for name, oid in fields.status_option_ids.items():
            if name.strip().lower() == desired:
                option_id = oid
                break

    if option_id is None:
        available = ", ".join(sorted(fields.status_option_ids.keys()))
        raise RuntimeError(
            f"Status option '{status_value}' not found in project. "
            f"Available options: {available}"
        )

    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId,
        itemId: $itemId,
        fieldId: $fieldId,
        value: { singleSelectOptionId: $optionId }
      }) {
        projectV2Item {
          id
        }
      }
    }
    """
    graphql(
        mutation,
        {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": fields.status_field_id,
            "optionId": option_id,
        },
    )


# --------------------------------------------------------------------------- #
# Issues + status inference                                                   #
# --------------------------------------------------------------------------- #


def search_issues(repo_full_name: str, label: str) -> list[dict[str, Any]]:
    """
    Use the Search API to find issues with the given label.

    Note:
        This currently fetches only the first page (100 results). If you ever
        have >100 issues per phase, extend this to paginate.
    """
    q = f"repo:{repo_full_name} is:issue label:\"{label}\""
    url = f"{GITHUB_API}/search/issues"
    data = rest_get(url, params={"q": q, "per_page": 100, "page": 1})
    return data.get("items", [])


def infer_status_for_issue(
    issue: dict[str, Any],
    status_cfg: StatusFieldConfig | None,
    status_mapping: dict[str, Any],
) -> str | None:
    """
    Infer the desired Status field value for an issue based on labels + state.

    Returns:
        The Status option value to use (e.g. "Backlog"), or None if no change
        should be made.
    """
    if status_cfg is None:
        return None

    labels = {l["name"] for l in issue.get("labels", [])}
    state = issue.get("state", "open")

    default_state = status_mapping.get("default_state", status_cfg.backlog)
    in_progress_state = status_mapping.get("in_progress_state", status_cfg.in_progress)
    done_state = status_mapping.get("done_state", status_cfg.done)

    in_progress_labels = set(status_mapping.get("in_progress_labels", []))
    done_labels = set(status_mapping.get("done_labels", []))

    # Closed issues are considered done regardless of labels.
    if state == "closed":
        return done_state

    if labels & done_labels:
        return done_state

    if labels & in_progress_labels:
        return in_progress_state

    return default_state


# --------------------------------------------------------------------------- #
# Main sync                                                                   #
# --------------------------------------------------------------------------- #


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: sync_project.py .github/project-roadmap.yml")

    cfg_path = sys.argv[1]
    (
        project_cfg,
        repo_full_name,
        phases,
        status_cfg,
        status_mapping,
    ) = load_config(cfg_path)

    print(f"Loaded config: project={project_cfg.name}, repo={repo_full_name}")

    project_id, project_number = find_or_create_project(project_cfg)
    print(f"Using projectV2 id={project_id}, number={project_number}")

    project_fields = get_project_fields(project_id, status_cfg)
    owner, name = repo_full_name.split("/", 1)

    for phase in phases:
        print(f"\nSyncing phase {phase.code} ({phase.label})")
        issues = search_issues(repo_full_name, phase.label)
        print(f"  Found {len(issues)} issues for label {phase.label}")

        for issue in issues:
            issue_number = issue["number"]
            query = """
            query($owner: String!, $name: String!, $number: Int!) {
              repository(owner: $owner, name: $name) {
                issue(number: $number) {
                  id
                  title
                }
              }
            }
            """
            data = graphql(
                query,
                {"owner": owner, "name": name, "number": int(issue_number)},
            )
            node = data["repository"]["issue"]
            if node is None:
                print(f"    Skipping issue #{issue_number}: not found in GraphQL")
                continue

            print(f"    Adding issue #{issue_number} - {node['title']} to project")
            add_result = graphql(
                """
                mutation($projectId: ID!, $contentId: ID!) {
                  addProjectV2ItemById(input: {
                    projectId: $projectId,
                    contentId: $contentId
                  }) {
                    item { id }
                  }
                }
                """,
                {"projectId": project_id, "contentId": node["id"]},
            )
            item_id = add_result["addProjectV2ItemById"]["item"]["id"]

            desired_status = infer_status_for_issue(issue, status_cfg, status_mapping)
            if desired_status is not None:
                print(f"      Setting Status = {desired_status}")
                set_status_for_item(project_id, item_id, project_fields, desired_status)

    print("\nSync complete.")


if __name__ == "__main__":
    main()
