"""Logging that cannot leak user input (spec 3.7). The app logs method, route template, status and timing only.
No query strings, no bodies, no IP addresses. A filter also redacts anything that looks like an echo of user text."""
import logging
import sys

REDACT_KEYS = ("material_description", "description", "q=", "text=")


class Redactor(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if any(k in msg for k in REDACT_KEYS):
            record.msg, record.args = "[redacted: possible user input]", ()
        return True


def setup():
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    h.addFilter(Redactor())
    root.addHandler(h)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True       # replaced by our own middleware line
    logging.getLogger("httpx").setLevel(logging.WARNING)
