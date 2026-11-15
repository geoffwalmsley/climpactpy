"""Settings for the browser test of the Content Security Policy with Cloudflare Turnstile
on (#137, test_accessibility.py): the local install, except that Turnstile is on, with
Cloudflare's published test keys (the widget always passes, on any host; no account), and
the policy is the one hosted mode sends with Turnstile keys set."""

from climpact_web.settings import *  # noqa: F403
from climpact_web.settings import content_security_policy

# Turnstile is on only in hosted mode (core/limits.py); nothing else here reads IS_HOSTED
# on the pages the test opens, and the rest of the hosted settings are left out.
IS_HOSTED = True
TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
TURNSTILE_SECRET_KEY = "1x0000000000000000000000000000000AA"
SECURE_CSP = content_security_policy(turnstile=True)
SECURE_CSP_REPORT_ONLY = {}
