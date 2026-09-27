"""Shared HTTP session.

truststore makes Python use the Windows certificate store, so HTTPS works
behind antivirus/proxies that inspect TLS traffic.
"""
import truststore

truststore.inject_into_ssl()

import requests  # noqa: E402

USER_AGENT = "Turrapportgenerator/0.1 (+https://github.com/dgdHermanJ/Turrapportgenerator)"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT
