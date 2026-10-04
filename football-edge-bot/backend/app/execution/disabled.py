from .base import BettingExecutor, ExecutionOrder

class DisabledExecutor(BettingExecutor):
    async def place_order(self, order: ExecutionOrder) -> str:
        raise RuntimeError('Live execution is disabled in this MVP. Use the paper trader until a supported exchange/bookmaker adapter is explicitly configured.')

    async def get_balance(self) -> float:
        return 0.0
