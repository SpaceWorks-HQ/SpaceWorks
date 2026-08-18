"""Renewable, fenced leases for slow tenant-object promotion calls."""

import logging
from threading import Event, Lock, Thread

from django.db import close_old_connections
from django.utils import timezone

from .insertion_errors import ImportPromotionClaimLost
from .models_import_objects import TenantImportObject


logger = logging.getLogger(__name__)


class PromotionClaimHeartbeat:
    """Keep one claim live while object storage performs a blocking copy."""

    def __init__(self, row_id, claimed_at, *, lease_duration):
        self.row_id = row_id
        self.claimed_at = claimed_at
        self.interval = max(lease_duration.total_seconds() / 3, 0.01)
        self._stop = Event()
        self._lock = Lock()
        self._lost = False
        self._thread = Thread(
            target=self._run,
            name=f"tenant-import-promotion-{row_id}",
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self._stop.set()
        self._thread.join()
        if self._lost:
            raise ImportPromotionClaimLost(
                f"Object promotion claim {self.row_id} was superseded."
            )
        return False

    def _run(self):
        close_old_connections()
        try:
            while not self._stop.wait(self.interval):
                if not self._renew_once():
                    return
        finally:
            close_old_connections()

    def _renew_once(self):
        """Renew the claim. Return False only when the claim is genuinely gone.

        A renewal error is NOT a lost claim: the fenced compare-and-swap in the
        promotion write remains the authority on ownership. But it must not end the
        heartbeat either -- abandoning renewal lets the recovery sweep treat this
        live worker as stale and start a second one, which duplicates the object
        copy. The fence still keeps the journal correct; the wasted external work is
        what retrying here avoids. So a transient failure drops one beat and the
        loop keeps going until the copy finishes or the claim is really taken.
        """
        with self._lock:
            expected = self.claimed_at
        renewed_at = timezone.now()
        try:
            updated = TenantImportObject.objects.filter(
                pk=self.row_id,
                state=TenantImportObject.State.STAGED,
                claimed_at=expected,
            ).update(claimed_at=renewed_at, updated_at=renewed_at)
        except Exception:
            logger.warning(
                "tenant_import_promotion_heartbeat_failed",
                extra={"tenant_import_object_id": self.row_id},
                exc_info=True,
            )
            close_old_connections()
            return True
        if updated != 1:
            self._lost = True
            logger.warning(
                "tenant_import_promotion_claim_lost",
                extra={"tenant_import_object_id": self.row_id},
            )
            return False
        with self._lock:
            self.claimed_at = renewed_at
        return True
