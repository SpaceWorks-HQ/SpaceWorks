from rest_framework.throttling import SimpleRateThrottle


class MemberImagePresignThrottle(SimpleRateThrottle):
    """Per-member cap on profile image presign requests.

    A presigned upload hands out write access to an object key BEFORE any row claims it,
    and nothing forces the caller to come back and attach. In POST mode the presign
    targets the final key directly, so an unattached upload lands in the served
    `member/<makerspace_id>/...` namespace holding storage that no row can name: the
    purge collectors and `recompute_storage` both walk *rows*, and `limits.add_storage`
    is charged at attach, so an orphan is invisible to the quota, the reconciler and
    every purge path at once.

    Every public-image presign on the platform has this property; what makes this one
    worth capping is that it is the only one reachable by an ordinary member rather than
    a staff action. The cap bounds how much a single member can strand -- it does not
    make orphans impossible, which needs either a staging-prefix upload with a bucket
    lifecycle rule or a sweeper for unclaimed keys. Both are platform-wide changes to
    every image path and are deliberately left to their own phase.

    Keyed on the user, not the IP: the endpoint requires an active membership, so the
    account is the actor and a member on a shared or rotating address must not be able
    to spend somebody else's budget -- nor escape their own by changing networks.
    The cap is global only when a shared cache is configured (see ``CACHES``); LocMem
    is equivalent on a single-process deployment.

    POST only. Sharing one bucket with the attach and clear methods on the same view
    would make a normal edit -- presign, then attach -- spend two of the allowance, and
    would let a member who uploads their allowance lose the ability to *clear* an image,
    which is the one action that frees storage.
    """

    scope = "member_image_presign"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}
