# src/stacklion_api/adapters/uow/__init__.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Unit of Work implementations (Adapters Layer)

Purpose:
    Provide concrete UnitOfWork implementations backed by infrastructure
    concerns such as SQLAlchemy AsyncSession. Application-layer code must
    depend only on the `UnitOfWork` protocol from
    `stacklion_api.application.uow`.

Exports:
    - SqlAlchemyUnitOfWork: SQLAlchemy-backed UnitOfWork suitable for use
      in FastAPI dependencies and other adapter wiring.
"""

from __future__ import annotations

from .sqlalchemy_uow import SqlAlchemyUnitOfWork

__all__ = ["SqlAlchemyUnitOfWork"]
