from __future__ import annotations

import unittest
from collections.abc import Sequence

from backend.app.advanced.browser_network import (
    BrowserNetworkPolicy,
    StaticBrowserAddressResolver,
)
from backend.app.advanced.harness import PolicyViolation


_PUBLIC_ADDRESS = "93.184.216.34"


class BrowserNetworkPolicyTest(unittest.TestCase):
    def test_accepts_public_dns_and_keeps_url_out_of_repr(self) -> None:
        policy = BrowserNetworkPolicy(
            StaticBrowserAddressResolver(
                {"public.example.test": (_PUBLIC_ADDRESS,)}
            )
        )

        decision = policy.validate_url(
            "HTTPS://PUBLIC.EXAMPLE.TEST:443/guide?q=agent"
        )

        self.assertEqual("https://public.example.test", decision.origin)
        self.assertEqual((_PUBLIC_ADDRESS,), decision.addresses)
        self.assertEqual(
            "https://public.example.test/guide?q=agent",
            decision.canonical_url,
        )
        self.assertNotIn("guide?q=agent", repr(decision))

    def test_rejects_literal_non_public_address_classes(self) -> None:
        policy = BrowserNetworkPolicy(StaticBrowserAddressResolver({}))
        cases = (
            ("https://127.0.0.1/", "browser_localhost_not_allowed"),
            ("https://10.0.0.1/", "browser_address_not_allowed"),
            ("https://172.16.0.1/", "browser_address_not_allowed"),
            ("https://192.168.0.1/", "browser_address_not_allowed"),
            ("https://169.254.169.254/latest/meta-data", "browser_address_not_allowed"),
            ("https://0.0.0.0/", "browser_address_not_allowed"),
            ("https://100.64.0.1/", "browser_address_not_allowed"),
            ("https://192.0.2.1/", "browser_address_not_allowed"),
            ("https://224.0.0.1/", "browser_address_not_allowed"),
            ("https://[::1]/", "browser_localhost_not_allowed"),
            ("https://[fe80::1]/", "browser_address_not_allowed"),
            ("https://[fc00::1]/", "browser_address_not_allowed"),
        )

        for url, expected_code in cases:
            with self.subTest(url=url):
                with self.assertRaises(PolicyViolation) as raised:
                    policy.validate_url(url)
                self.assertEqual(expected_code, raised.exception.code)

    def test_rejects_any_private_or_invalid_dns_answer(self) -> None:
        cases = (
            ((_PUBLIC_ADDRESS, "10.0.0.8"), "browser_address_not_allowed"),
            ((), "browser_dns_invalid_response"),
            (("not-an-address",), "browser_dns_invalid_response"),
            (("fe80::1%eth0",), "browser_dns_invalid_response"),
        )

        for addresses, expected_code in cases:
            with self.subTest(addresses=addresses):
                policy = BrowserNetworkPolicy(
                    StaticBrowserAddressResolver(
                        {"public.example.test": addresses}
                    )
                )
                with self.assertRaises(PolicyViolation) as raised:
                    policy.validate_url("https://public.example.test/")
                self.assertEqual(expected_code, raised.exception.code)

    def test_reresolves_each_redirect_and_blocks_dns_rebinding(self) -> None:
        resolver = _SequenceResolver(
            ((_PUBLIC_ADDRESS,), ("169.254.169.254",))
        )
        policy = BrowserNetworkPolicy(resolver)
        start = "https://public.example.test/start"

        with self.assertRaises(PolicyViolation) as raised:
            policy.validate_navigation_chain(
                start,
                {start: "https://public.example.test/final"},
            )

        self.assertEqual("browser_address_not_allowed", raised.exception.code)
        self.assertEqual(2, resolver.calls)

    def test_validates_every_safe_redirect_and_rejects_loops(self) -> None:
        resolver = _SequenceResolver(
            ((_PUBLIC_ADDRESS,), (_PUBLIC_ADDRESS,))
        )
        policy = BrowserNetworkPolicy(resolver)
        start = "https://public.example.test/start"
        final = "https://public.example.test/final"

        decisions = policy.validate_navigation_chain(start, {start: final})

        self.assertEqual([start, final], [item.canonical_url for item in decisions])
        self.assertEqual(2, resolver.calls)

        loop_policy = BrowserNetworkPolicy(
            StaticBrowserAddressResolver(
                {"public.example.test": (_PUBLIC_ADDRESS,)}
            )
        )
        with self.assertRaises(PolicyViolation) as raised:
            loop_policy.validate_navigation_chain(
                start,
                {start: final, final: start},
            )
        self.assertEqual("browser_redirect_loop", raised.exception.code)

    def test_rejects_redirect_chains_over_the_configured_limit(self) -> None:
        policy = BrowserNetworkPolicy(
            StaticBrowserAddressResolver(
                {"public.example.test": (_PUBLIC_ADDRESS,)}
            ),
            max_redirects=1,
        )
        start = "https://public.example.test/start"
        middle = "https://public.example.test/middle"
        final = "https://public.example.test/final"

        with self.assertRaises(PolicyViolation) as raised:
            policy.validate_navigation_chain(
                start,
                {start: middle, middle: final},
            )

        self.assertEqual("browser_redirect_limit", raised.exception.code)


class _SequenceResolver:
    def __init__(self, responses: Sequence[Sequence[str]]) -> None:
        self._responses = tuple(tuple(item) for item in responses)
        self.calls = 0

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        del hostname, port
        if self.calls >= len(self._responses):
            raise OSError("no resolver response")
        response = self._responses[self.calls]
        self.calls += 1
        return response


if __name__ == "__main__":
    unittest.main()
