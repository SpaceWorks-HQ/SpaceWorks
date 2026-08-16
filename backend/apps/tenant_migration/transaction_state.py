from django.db import connections

from .insertion_errors import ImportTransactionRequired


def require_import_transaction(using="default"):
    """Require the caller to own the transaction spanning the complete import.

    Import infrastructure deliberately never opens or commits a transaction. A failure
    after any insert must roll every row back together; partial immutable/PROTECT-linked
    graphs require privileged trigger-bypass cleanup and are not a recoverable state.
    """
    connection = connections[using]
    if connection.get_autocommit() or not connection.in_atomic_block:
        raise ImportTransactionRequired(
            "Tenant insertion requires one caller-owned transaction."
        )
    return connection
