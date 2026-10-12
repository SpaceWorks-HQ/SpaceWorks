"""Filter keys shared by saved report preferences and schedules."""


def allowed_report_filters(report_key):
    keys = {"start", "end"}
    if report_key == "member-retention":
        keys.add("months")
    if report_key == "payment-reconciliation":
        keys.update(["status", "subject_type"])
    return keys
