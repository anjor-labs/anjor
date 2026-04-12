"""ProxyInterceptor — mitmproxy sidecar stub (optional Phase 1 extra).

Install the [proxy] extra to use: pip install anjor[proxy]
"""

from __future__ import annotations

from anjor.interceptors.base import BaseInterceptor


class ProxyInterceptor(BaseInterceptor):
    """Stub for mitmproxy-based interception on :7842."""

    @property
    def is_installed(self) -> bool:
        return False

    def install(self) -> None:
        raise NotImplementedError(
            "ProxyInterceptor requires mitmproxy. "
            "Install with: pip install anjor[proxy]"
        )

    def uninstall(self) -> None:
        pass
