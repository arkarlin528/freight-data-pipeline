from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from freight_pipeline.reference import CARRIERS, CONTAINER_TYPES, PORTS


@dataclass(frozen=True)
class RawRecord:
    """One row exactly as extracted: strings only, plus where it came from (for traceability)."""

    source: str
    ref: str  # e.g. "asl/page-2.html#row-14"
    fields: dict[str, str]


Money = Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), max_digits=12, decimal_places=2)]


class Rate(BaseModel):
    """A validated, normalised rate. Anything that can't become one of these is rejected with a reason."""

    model_config = ConfigDict(frozen=True)

    carrier: str
    origin: str = Field(pattern=r"^[A-Z]{5}$")
    destination: str = Field(pattern=r"^[A-Z]{5}$")
    container_type: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Money
    valid_from: date
    valid_to: date
    source_ref: str

    @model_validator(mode="after")
    def check_business_rules(self) -> Rate:
        if self.carrier not in CARRIERS:
            raise ValueError(f"unknown carrier {self.carrier}")
        for port in (self.origin, self.destination):
            if port not in PORTS:
                raise ValueError(f"unknown port {port}")
        if self.origin == self.destination:
            raise ValueError("origin and destination are the same port")
        if self.container_type not in CONTAINER_TYPES:
            raise ValueError(f"unsupported container type {self.container_type}")
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        return self

    @property
    def key(self) -> tuple[str, str, str, str, date]:
        """Natural key: one price per carrier, lane, container type and validity start."""
        return (self.carrier, self.origin, self.destination, self.container_type, self.valid_from)


@dataclass(frozen=True)
class Rejection:
    source: str
    ref: str
    reason: str
    raw: dict[str, str]


@dataclass
class TransformResult:
    rates: list[Rate] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    duplicates: int = 0
