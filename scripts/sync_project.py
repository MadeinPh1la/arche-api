#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests
import yaml

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"


@dataclass
class PhaseConfig:
    code: str
    milestone: str
    label: str
    default_status: str


@dataclass
class ProjectConfig:
    owner: str
    owner_type: str  # "USER" or "ORGANIZATION"
    name: str
    project_number: int | None


def load_config(path: str) -> tuple[ProjectConfig, str, list[PhaseConfig]]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    project_cfg = cfg["project"]
    repo_cfg = cfg["repository"]
    phases_cfg = cfg["phases"]

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

    return project, repo_full_name, phases


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


def find_or_create_project(config: ProjectConfig) -> tuple[str, int]:
    """
    Returns (project_id, project_number) for Projects v2.
    """

    # If project_number is pinned, try to fetch it directly.
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
        data = graphql(
            query, {"owner": config.owner, "number": config.project_number}
        )
        project = data["user"]["projectV2"]
        if project is None:
            raise RuntimeError(
                f"Project number {config.project_number} not found for {config.owner}"
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
        data = graphql(query, {"owner": config.owner})
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
        data = graphql(query, {"owner": config.owner})
        nodes = data["organization"]["projectsV2"]["nodes"]

    for node in nodes:
        if node["title"] == config.name:
            return node["id"], node["number"]

    # Create new project
    if config.owner_type.upper() == "USER":
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
        # Need the user ID first
        owner_query = """
        query($login: String!) {
          user(login: $login) { id }
        }
        """
        owner_data = graphql(owner_query, {"login": config.owner})
        owner_id = owner_data["user"]["id"]
    else:
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
        owner_query = """
        query($login: String!) {
          organization(login: $login) { id }
        }
        """
        owner_data = graphql(owner_query, {"login": config.owner})
        owner_id = owner_data["organization"]["id"]

    create_data = graphql(mutation, {"ownerId": owner_id, "title": config.name})
    proj = create_data["createProjectV2"]["projectV2"]
    return proj["id"], proj["number"]


def search_issues(repo_full_name: str, label: str) -> list[dict[str, Any]]:
    """
    Use the Search API to find issues with the given label.
    """
    q = f"repo:{repo_full_name} is:issue label:\"{label}\""
    url = f"{GITHUB_API}/search/issues"
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        data = rest_get(url, params={"q": q, "per_page": 100, "page": page})
        items.extend(data.get("items", []))
        if "next" not in (requests.utils.parse_header_links(resp := None) if False else {}):
            # Cheap: stop at first page; you can extend this later if you expect >100 issues per phase.
            break
        page += 1
    return items


def add_issue_to_project(project_id: str, issue_node_id: str) -> None:
    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {
        projectId: $projectId,
        contentId: $contentId
      }) {
        item {
          id
        }
      }
    }
    """
    graphql(mutation, {"projectId": project_id, "contentId": issue_node_id})


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: sync_project.py .github/project-roadmap.yml")

    cfg_path = sys.argv[1]
    project_cfg, repo_full_name, phases = load_config(cfg_path)
    print(f"Loaded config: project={project_cfg.name}, repo={repo_full_name}")

    project_id, project_number = find_or_create_project(project_cfg)
    print(f"Using projectV2 id={project_id}, number={project_number}")

    # For each phase, find issues by label and add to project.
    # NOTE: Search API returns REST issue objects; we need GraphQL node IDs for addProjectV2ItemById.
    # We'll fetch node IDs via a secondary GraphQL query by issue number.
    for phase in phases:
        print(f"\nSyncing phase {phase.code} ({phase.label})")
        issues = search_issues(repo_full_name, phase.label)
        print(f"  Found {len(issues)} issues for label {phase.label}")

        for issue in issues:
            issue_number = issue["number"]
            # GraphQL query to get the node ID
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
            owner, name = repo_full_name.split("/", 1)
            data = graphql(
                query,
                {"owner": owner, "name": name, "number": int(issue_number)},
            )
            node = data["repository"]["issue"]
            if node is None:
                print(f"    Skipping issue #{issue_number}: not found in GraphQL")
                continue

            print(f"    Adding issue #{issue_number} - {node['title']} to project")
            add_issue_to_project(project_id, node["id"])

    print("\nSync complete.")


if __name__ == "__main__":
    main()
