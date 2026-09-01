class EventInvalidTransition(Exception):
    pass


class CapacityConflict(Exception):
    pass


class RegistrationClosed(Exception):
    pass


class RegistrationRejected(Exception):
    pass


class DuplicateRegistration(Exception):
    def __init__(self, *args, fresh_status=None):
        super().__init__(*args)
        self.fresh_status = fresh_status
