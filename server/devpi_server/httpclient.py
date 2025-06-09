from __future__ import annotations

from . import __version__ as server_version
from .exceptions import lazy_format_exception_only
from .log import threadlog
from devpi_common.types import cached_property
from devpi_common.url import URL
from requests.utils import DEFAULT_CA_BUNDLE_PATH
from typing import TYPE_CHECKING
import httpx
import inspect
import os
import ssl
import sys


if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import ExitStack


def get_caller_location(stacklevel: int = 2) -> str:
    frame = inspect.currentframe()
    if frame is None:
        return "unknown (no current frame)"
    while frame and stacklevel:
        frame = frame.f_back
        stacklevel -= 1
    if frame is None:
        return f"unknown (stacklevel {stacklevel})"
    return f"{frame.f_code.co_filename}:{frame.f_lineno}::{frame.f_code.co_name}"


class FatalResponse:
    status_code = -1

    def __init__(self, url: URL | str, reason: str):
        self.url = url
        self.reason = reason
        self.reason_phrase = reason
        self.status = self.status_code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.reason!r})"

    # an adapter to allow this to be used in async_get
    def __iter__(self) -> Iterator:
        yield self
        yield self.reason

    def close(self) -> None:
        pass


class HTTPClient:
    Errors = (
        OSError,
        httpx.HTTPError,
        httpx.RequestError,
        httpx.StreamError,
    )

    def __init__(self, *, component_name: str, timeout: int | None) -> None:
        self.headers = {"User-Agent": f"devpi-{component_name}/{server_version}"}
        self.client = httpx.Client(headers=self.headers, verify=self._ssl_context)
        self.timeout = timeout

    @cached_property
    def _ssl_context(self) -> ssl.SSLContext:
        # create an SSLContext object that uses the same CA certs as requests
        cafile = (
            os.environ.get("REQUESTS_CA_BUNDLE")
            or os.environ.get("CURL_CA_BUNDLE")
            or DEFAULT_CA_BUNDLE_PATH
        )
        if cafile and not os.path.exists(cafile):
            threadlog.warning(
                "Could not find a suitable TLS CA certificate bundle, invalid path: %s",
                cafile,
            )
            cafile = None

        return ssl.create_default_context(cafile=cafile)

    def async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self.headers, verify=self._ssl_context)

    async def async_get(
        self,
        url: URL | str,
        *,
        allow_redirects: bool,
        timeout: int | None = None,
        extra_headers: dict | None = None,
    ) -> tuple[httpx.Response, str | None] | FatalResponse:
        try:
            async with self.async_client() as client:
                response = await client.get(
                    url.url if isinstance(url, URL) else url,
                    follow_redirects=allow_redirects,
                    headers=extra_headers,
                    timeout=timeout or self.timeout,
                )
                text = response.text if response.status_code < 300 else None
                return response, text
        except self.Errors as e:
            location = get_caller_location()
            threadlog.warn(
                "%s during http.async_get of %s at %s: %s",
                e.__class__.__name__,
                url,
                location,
                lazy_format_exception_only(e),
            )
            return FatalResponse(url, repr(sys.exc_info()[1]))

    def close(self) -> None:
        self.client.close()

    def get(
        self,
        url: URL | str,
        *,
        allow_redirects: bool,
        timeout: int | None = None,
        extra_headers: dict | None = None,
    ) -> httpx.Response | FatalResponse:
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self.client.get(
                url.url if isinstance(url, URL) else url,
                follow_redirects=allow_redirects,
                headers=headers,
                timeout=timeout or self.timeout,
            )
        except self.Errors as e:
            location = get_caller_location()
            threadlog.warn(
                "%s during http.stream of %s at %s: %s",
                e.__class__.__name__,
                url,
                location,
                lazy_format_exception_only(e),
            )
            return FatalResponse(url, repr(sys.exc_info()[1]))
        else:
            return resp

    def post(
        self,
        url: URL | str,
        *,
        data: dict | None = None,
        files: dict | None = None,
        timeout: int | None = None,
        extra_headers: dict | None = None,
    ) -> httpx.Response | FatalResponse:
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self.client.post(
                url.url if isinstance(url, URL) else url,
                data=data,
                files=files,
                headers=headers,
                timeout=timeout or self.timeout,
            )
        except self.Errors as e:
            location = get_caller_location()
            threadlog.warn(
                "%s during http.stream of %s at %s: %s",
                e.__class__.__name__,
                url,
                location,
                lazy_format_exception_only(e),
            )
            return FatalResponse(url, repr(sys.exc_info()[1]))
        else:
            return resp

    def stream(
        self,
        cstack: ExitStack,
        method: str,
        url: URL | str,
        *,
        allow_redirects: bool,
        content: bytes | None = None,
        timeout: int | None = None,
        extra_headers: dict | None = None,
    ) -> httpx.Response | FatalResponse:
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        try:
            gen = self.client.stream(
                method,
                url.url if isinstance(url, URL) else url,
                content=content,
                follow_redirects=allow_redirects,
                headers=headers,
                timeout=timeout or self.timeout,
            )
            resp = cstack.enter_context(gen)
        except self.Errors as e:
            location = get_caller_location()
            threadlog.warn(
                "%s during http.stream of %s at %s: %s",
                e.__class__.__name__,
                url,
                location,
                lazy_format_exception_only(e),
            )
            return FatalResponse(url, repr(sys.exc_info()[1]))
        else:
            return resp


class OfflineHTTPClient:
    def close(self) -> None:
        pass

    def _resp(self, url: str) -> FatalResponse:
        resp = FatalResponse(url, "Service Unavailable")
        resp.status_code = 503
        return resp

    def get(
        self,
        url: URL | str,
        *,
        allow_redirects: bool,  # noqa: ARG002
        timeout: int | None = None,  # noqa: ARG002
        extra_headers: dict | None = None,  # noqa: ARG002
    ) -> FatalResponse:
        if isinstance(url, URL):
            return self._resp(url.url)
        return self._resp(url)

    def stream(
        self,
        cstack: ExitStack,  # noqa: ARG002
        method: str,  # noqa: ARG002
        url: URL | str,
        *,
        allow_redirects: bool,  # noqa: ARG002
        timeout: int | None = None,  # noqa: ARG002
        extra_headers: dict | None = None,  # noqa: ARG002
    ) -> FatalResponse:
        if isinstance(url, URL):
            return self._resp(url.url)
        return self._resp(url)
