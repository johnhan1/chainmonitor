from __future__ import annotations


class IngestionFetchError(RuntimeError):
    def __init__(
        self,
        reason: str,
        detail: str,
        chain_id: str,
        trace_id: str,
    ) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.chain_id = chain_id
        self.trace_id = trace_id
