"""WP4 read-only public discoveries; member mutations require session identity."""


def definitions(read_scopes, write_scopes, slug_mode):
    return tuple((name, ("GET", "HEAD"), read_scopes, slug_mode, False, False)
                 for name in ("public-machine-detail", "public-machine-details", "public-machine-intake")) + tuple(
        (name, ("POST", "DELETE"), write_scopes, slug_mode, False, False)
        for name in ("public-inventory-watch", "v1:public-inventory-watch"))
