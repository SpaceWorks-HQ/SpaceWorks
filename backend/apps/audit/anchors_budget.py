"""A per-attempt cap on application-level anchor sink reads.

One budget is created per verification attempt and threaded through every sink read in
that attempt, including the nested list pages and transition fetches made while resolving
a scope head. It counts operations the application issues, not wire retries hidden inside
an SDK. Exhaustion is a resource limit, deliberately NOT an ``AnchorError``: a broad
``except AnchorError`` must never turn "we stopped on purpose" into "the anchor is down".
"""


class AnchorReadBudgetExceeded(RuntimeError):
    pass


class AnchorReadBudget:
    def __init__(self, limit):
        if int(limit) < 0:
            raise ValueError("An anchor read budget cannot be negative.")
        self.limit = int(limit)
        self.used = 0

    @property
    def remaining(self):
        return self.limit - self.used

    def consume(self):
        """Call immediately BEFORE a provider operation; refuses the operation over the cap."""
        if self.used >= self.limit:
            raise AnchorReadBudgetExceeded(
                f"The anchor read budget of {self.limit} operations is exhausted."
            )
        self.used += 1


def consume(budget):
    if budget is not None:
        budget.consume()
