#!/usr/bin/env python3
"""
MCP Smoke Test Script for Arche.

This script exercises the Arche MCP HTTP endpoint end-to-end using a
simple MCP envelope over HTTP POST.

Contract:

    POST /mcp
        Request body:
            {
              "method": "system.health",
              "params": { ... } | null
            }

        Response body:
            {
              "result": { ... } | null,
              "error":  { ... } | null
            }

Usage (from the project root):

    python -m scripts.mcp_smoke_test

You can override configuration via CLI flags or environment variables:

    - MCP_HTTP_BASE_URL (default: http://127.0.0.1:8000)
    - MCP_HTTP_API_KEY   (optional; used as X-Api-Key header)

Examples:

    python -m scripts.mcp_smoke_test

    MCP_HTTP_BASE_URL=http://127.0.0.1:8000 \
    MCP_HTTP_API_KEY=__dev_mcp__ \
    python -m scripts.mcp_smoke_test --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

JSON = dict[str, Any]


@dataclass
class SmokeTestConfig:
    """Configuration for MCP smoke tests.

    Attributes:
        base_url: Base URL of the Arche HTTP API (without trailing slash).
        mcp_path: Path to the MCP HTTP entrypoint (e.g., "/mcp").
        api_key: Optional API key to send as `X-Api-Key`.
        timeout_s: HTTP request timeout in seconds.
        verify_ssl: Whether to verify TLS certificates for HTTPS URLs.
        verbose: Whether to print raw request/response payloads.
    """

    base_url: str
    mcp_path: str = "/mcp"
    api_key: str | None = None
    timeout_s: float = 10.0
    verify_ssl: bool = True
    verbose: bool = False


class MCPClientError(RuntimeError):
    """Raised when the MCP client encounters an unrecoverable error."""


class MCPServerError(RuntimeError):
    """Raised when the MCP server returns an error response."""


class MCPClient:
    """Minimal MCP HTTP client for Arche.

    This client speaks a simple MCP envelope over HTTP POST:

        Request:  { "method": str, "params": dict | null }
        Response: { "result": any | null, "error": MCPError | null }

    It is intentionally small and self-contained, suitable for smoke testing
    and diagnostics rather than production use.
    """

    def __init__(self, config: SmokeTestConfig) -> None:
        """Initialize the MCP client.

        Args:
            config: SmokeTestConfig instance specifying base URL, MCP path,
                API key, timeouts, and logging verbosity.
        """
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_s,
            verify=config.verify_ssl,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def call(self, method: str, params: JSON | None = None) -> JSON:
        """Call an MCP method.

        Args:
            method: MCP method name (e.g., "system.health").
            params: Optional dictionary of parameters for the method.

        Returns:
            The `result` object from the MCP response.

        Raises:
            MCPClientError: If the HTTP request fails or the response is not
                valid JSON or missing expected fields.
            MCPServerError: If the server returns an `error` object.
        """
        if params is None:
            params = {}

        payload: JSON = {
            "method": method,
            "params": params or None,
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["X-Api-Key"] = self._config.api_key

        if self._config.verbose:
            print(f"\n=== MCP REQUEST: {method} ===")
            print(json.dumps(payload, indent=2, sort_keys=True))

        try:
            response = await self._client.post(
                self._config.mcp_path,
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise MCPClientError(
                f"HTTP request to MCP endpoint failed: {exc}",
            ) from exc

        if response.status_code != 200:
            raise MCPClientError(
                f"Unexpected HTTP status from MCP endpoint: "
                f"{response.status_code} {response.reason_phrase}",
            )

        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise MCPClientError(
                f"Invalid JSON response from MCP endpoint: {exc}",
            ) from exc

        if self._config.verbose:
            print(f"\n=== MCP RESPONSE: {method} ===")
            print(json.dumps(body, indent=2, sort_keys=True))

        if not isinstance(body, dict):
            raise MCPClientError(f"Invalid MCP response envelope: {body!r}")

        if "result" not in body or "error" not in body:
            raise MCPClientError(
                f"MCP response missing 'result'/'error' fields: {body!r}",
            )

        error = body.get("error")
        if error is not None:
            # Shape depends on MCPError; we at least surface type/message.
            err_type = error.get("type", "UNKNOWN")
            message = error.get("message", "Unknown MCP error")
            raise MCPServerError(
                f"MCP method '{method}' returned error {err_type}: {message}",
            )

        return body["result"]


async def run_smoke_tests(config: SmokeTestConfig) -> int:
    """Run a sequence of MCP smoke tests against the Arche endpoint.

    Args:
        config: SmokeTestConfig instance with connection parameters.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    client = MCPClient(config)

    try:
        print(f"▶ Using MCP URL: {config.base_url}{config.mcp_path}")
        if config.api_key:
            print("▶ Using X-Api-Key from configuration.")
        else:
            print("▶ No API key configured (MCP endpoint must be open in dev).")

        print("\n[1/4] Calling system.health ...")
        health = await client.call("system.health", {})
        print("✓ system.health result:")
        print(json.dumps(health, indent=2, sort_keys=True))

        print("\n[2/4] Calling system.metadata ...")
        metadata = await client.call("system.metadata", {})
        print("✓ system.metadata result:")
        print(json.dumps(metadata, indent=2, sort_keys=True))

        print("\n[3/4] Calling quotes.live for AAPL, MSFT ...")
        live_quotes = await client.call(
            "quotes.live",
            {"tickers": ["AAPL", "MSFT"]},
        )
        print("✓ quotes.live result:")
        print(json.dumps(live_quotes, indent=2, sort_keys=True))

        print("\n[4/4] Calling quotes.historical for MSFT ...")
        historical = await client.call(
            "quotes.historical",
            {
                "tickers": ["MSFT"],
                "from": "2024-01-01",
                "to": "2024-01-05",
                "interval": "1d",
                "page": 1,
                "page_size": 50,
            },
        )
        print("✓ quotes.historical result:")
        print(json.dumps(historical, indent=2, sort_keys=True))

        print("\n✅ MCP smoke tests completed successfully.")
        return 0

    except (MCPClientError, MCPServerError) as exc:
        print("\n❌ MCP smoke tests failed:", file=sys.stderr)
        print(f"   {exc}", file=sys.stderr)
        return 1

    finally:
        await client.aclose()


def parse_args(argv: list[str] | None = None) -> SmokeTestConfig:
    """Parse CLI arguments and environment variables into a SmokeTestConfig.

    Args:
        argv: Optional list of argument strings. If omitted, `sys.argv[1:]`
            is used.

    Returns:
        A populated SmokeTestConfig instance.
    """
    parser = argparse.ArgumentParser(
        description="Arche MCP HTTP smoke test (MCP envelope over POST).",
    )

    parser.add_argument(
        "--base-url",
        default=os.getenv("MCP_HTTP_BASE_URL", "http://127.0.0.1:8000"),
        help=(
            "Base URL for the Arche HTTP API " "(default: %(default)s or MCP_HTTP_BASE_URL)."
        ),
    )
    parser.add_argument(
        "--mcp-path",
        default=os.getenv("MCP_HTTP_PATH", "/mcp"),
        help="Path to the MCP HTTP entrypoint (default: %(default)s).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MCP_HTTP_API_KEY"),
        help=("API key to send as X-Api-Key header " "(default: MCP_HTTP_API_KEY env var)."),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("MCP_HTTP_TIMEOUT_S", "10.0")),
        help="HTTP request timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable TLS certificate verification (for local HTTPS dev only).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print raw MCP request and response payloads.",
    )

    args = parser.parse_args(argv)

    return SmokeTestConfig(
        base_url=args.base_url.rstrip("/"),
        mcp_path=args.mcp_path if args.mcp_path.startswith("/") else f"/{args.mcp_path}",
        api_key=args.api_key,
        timeout_s=args.timeout,
        verify_ssl=not args.no - verify_ssl if hasattr(args, "no-verify_ssl") else not args.no_verify_ssl,  # type: ignore[attr-defined]
        verbose=bool(args.verbose),
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for the MCP smoke test script.

    Args:
        argv: Optional list of argument strings. If omitted, `sys.argv[1:]`
            is used.
    """
    config = parse_args(argv)
    exit_code = asyncio.run(run_smoke_tests(config))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
