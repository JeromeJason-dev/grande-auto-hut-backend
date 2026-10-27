import hashlib

from rest_framework.throttling import SimpleRateThrottle


class _IPThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _EmailThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        email = str(getattr(request, "data", {}).get("email", "") or "").strip().lower()
        if not email:
            return None  # nothing to key on; the IP throttle still applies
        digest = hashlib.sha256(email.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class LoginIPThrottle(_IPThrottle):
    scope = "login_ip"


class LoginEmailThrottle(_EmailThrottle):
    scope = "login_email"


class RegisterThrottle(_IPThrottle):
    scope = "register"


class PasswordResetIPThrottle(_IPThrottle):
    scope = "password_reset"


class PasswordResetEmailThrottle(_EmailThrottle):
    scope = "password_reset"


class EmailVerifyThrottle(_IPThrottle):
    scope = "email_verify"