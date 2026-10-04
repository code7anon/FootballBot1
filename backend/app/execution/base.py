from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ExecutionOrder:
    fixture_external_id: str
    market: str
    selection: str
    odds: float
    stake: float

class BettingExecutor(ABC):
    """Provider-neutral execution interface. Live money is intentionally not wired into the MVP."""

    @abstractmethod
    async def place_order(self, order: ExecutionOrder) -> str:
        raise NotImplementedError

    @abstractmethod
    async def get_balance(self) -> float:
        raise NotImplementedError
