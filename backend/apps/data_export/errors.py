"""Typed failures shared by export readers and archive projections."""


class ExportIntegrityError(RuntimeError):
    """The source snapshot cannot be represented without losing integrity."""
