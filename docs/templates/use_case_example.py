# docs/templates/use_case_example.py
"""Example application use case.

Purpose:
- Show canonical pattern for application-layer use cases: request/response DTOs,
  execute(...) method, and UoW/repository orchestration.

Layer: application

Notes:
- No HTTP or ORM imports. Returns DTOs only; presenters own HTTP envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass

from arche_api.adapters.uow import UnitOfWork  # or application-level UoW interface
from arche_api.application.schemas.dto.base import BaseDTO
from arche_api.domain.exceptions import NotFoundException
from arche_api.domain.interfaces.repositories.market_data_repository import (
    MarketDataRepository,
)


@dataclass(frozen=True, slots=True)
class ExampleRequestDTO(BaseDTO):
    """Example request DTO for a use case.

    Args:
        ticker: Canonical ticker symbol.
    """

    ticker: str


@dataclass(frozen=True, slots=True)
class ExampleResponseDTO(BaseDTO):
    """Example response DTO from a use case.

    Args:
        ticker: Canonical ticker symbol.
        last_price: Last traded price represented as a decimal string.
    """

    ticker: str
    last_price: str


class GetExampleMetricUseCase:
    """Canonical use case that reads from a repository and returns a DTO.

    Args:
        uow: Unit-of-work for transactional orchestration.
        market_data_repo: Repository that provides market data access.

    Raises:
        NotFoundException: If the requested ticker does not exist.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        market_data_repo: MarketDataRepository,
    ) -> None:
        self._uow = uow
        self._market_data_repo = market_data_repo

    async def execute(self, request: ExampleRequestDTO) -> ExampleResponseDTO:
        """Execute the use case.

        Args:
            request: Validated request DTO.

        Returns:
            A populated response DTO representing the latest metric.

        Raises:
            NotFoundException: If the ticker cannot be found.
        """
        async with self._uow:
            quote = await self._market_data_repo.get_latest_quote(ticker=request.ticker)
            if quote is None:
                raise NotFoundException(f"ticker not found: {request.ticker}")

            return ExampleResponseDTO(
                ticker=quote.ticker,
                last_price=str(quote.last_price),
            )
