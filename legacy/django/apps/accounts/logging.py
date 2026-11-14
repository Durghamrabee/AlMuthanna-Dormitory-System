import logging
import re


class RedactRecoveryLinks(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"(/accounts/password/reset/)[^/\s]+/[^/\s]+/", r"\1[redacted]/[redacted]/", record.getMessage())
        record.args = ()
        return True
