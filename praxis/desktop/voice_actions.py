"""The conductor's hands: what the voice can do to PRAXIS. Thin and thread-safe; every call goes through the Controller's
locks, so a spoken command is exactly as safe as a typed or clicked one."""
from ..voice.narrator import describe_status

STRATEGY = {"quality": "measured", "balanced": "auto", "frugal": "frugal"}


class ControllerActions:
    def __init__(self, controller, on_mute=None):
        self.c, self.on_mute = controller, on_mute

    def pending(self):
        return self.c.pending_approvals()

    def state(self):
        return self.c.state

    def submit(self, text):
        return self.c.submit(text)

    def stop(self):
        self.c.stop()

    def respond(self, req_id, ok):
        self.c.respond(req_id, ok)

    def set_data(self, dc):
        self.c.set_data_class(dc)

    def set_frugality(self, key):
        self.c.set_strategy(STRATEGY[key])

    def resume(self):
        return self.c.resume()

    def mute(self):
        if self.on_mute:
            self.on_mute()

    def status_text(self):
        try:
            return describe_status(self.c.view_now(), self.c.state, self.c.pending_approvals())
        except Exception:
            return "I can't read my own status right now."
