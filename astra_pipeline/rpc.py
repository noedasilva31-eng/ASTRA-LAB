import uuid
from astra_blocks.rpc import Rpc
class QuotaExceeded(RuntimeError):pass
class BudgetRpc(Rpc):
    """One durable unit for every HTTP attempt, including context queries."""
    def __init__(self,budget,endpoint=None,timeout=8):
        super().__init__(endpoint,timeout);self.budget=budget
    def call(self,method,params):
        try:result=self.budget.reserve(uuid.uuid4().hex,1)
        except ValueError as exc:
            if str(exc)=='quota_exhausted':raise QuotaExceeded('quota_exhausted') from None
            raise
        if not result['authorized']:raise QuotaExceeded('request_already_reserved')
        # Never refund an uncertain request, including a timeout or process crash.
        return super().call(method,params)
