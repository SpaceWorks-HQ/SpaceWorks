"""Member calendar alarms use the same lead policy as event reminders."""

from datetime import timedelta

from apps.makerspaces.reminder_policy import reminder_offsets


def add_member_alarms(component, makerspace, title):
    from icalendar import Alarm

    for seconds in reminder_offsets(makerspace, "event"):
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", title)
        alarm.add("trigger", timedelta(seconds=seconds))
        component.add_component(alarm)
