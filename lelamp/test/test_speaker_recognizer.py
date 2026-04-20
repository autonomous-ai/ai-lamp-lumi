"""Manual integration test for the speaker recognition API.

Hits a running LeLamp server on http://localhost:5001 (override via
``LELAMP_URL``) using real WAV files under ``lelamp/test/mock_data/audio/``
to simulate both mic-originated and Telegram-originated enrollment /
recognition flows.

Not pytest — just functions that print results. Run with::

    cd lelamp
    PYTHONPATH=.. python -m test.test_speaker_recognizer

Prereqs:
    * LeLamp up on ``LELAMP_URL``
    * dlbackend up (speaker recognition needs its /embed endpoint)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

# ============================================================================
# Config — tweak via env vars or edit defaults below
# ============================================================================

# LeLamp API root (no trailing slash).
LELAMP_URL: str = os.environ.get("LELAMP_URL", "http://localhost:5001")

# How long to wait for each HTTP call.
HTTP_TIMEOUT_S: float = float(os.environ.get("LELAMP_TEST_TIMEOUT_S", "60"))

# Mock-data root — resolved relative to this file by default so running the
# script from anywhere works.
_HERE = Path(__file__).resolve().parent
MOCK_AUDIO_DIR: Path = Path(
    os.environ.get("LELAMP_TEST_AUDIO_DIR", _HERE / "mock_data" / "audio")
)

# Pick which files represent each scripted "speaker" in the flow.
DARREN_SAMPLES: list[str] = [
    "Darren/record_0.wav",
    "Darren/record_1.wav",
    "Darren/record_2.wav",
]
DARREN_PROBE: str = "Darren/record_3.wav"  # different file, expect match

KHANH_SAMPLES: list[str] = [
    "Khanh/Khanh_1.wav",
    "Khanh/Khanh_2.wav",
]
KHANH_PROBE: str = "Khanh/Khanh_3.wav"

BAO_SAMPLES: list[str] = [
    "Bao/Bao_1.wav",
]
BAO_PROBE: str = "Bao/Bao_2.wav"

# Known-noisy / unrecognized sample for unknown-speaker simulation.
UNKNOWN_PROBE: str = "soundscape.wav"

# Fake Telegram identity for the Telegram-origin enrollment case.
KHANH_TG_USERNAME: str = "khanh_tg"
KHANH_TG_ID: str = "111222333"

BAO_TG_USERNAME: str = "bao_tg"
BAO_TG_ID: str = "444555666"

# Reset at the start so repeated runs are deterministic.
RESET_BEFORE_RUN: bool = os.environ.get("LELAMP_TEST_RESET", "true").lower() == "true"

# In-memory test report for final PASS/FAIL summary.
TEST_RESULTS: list[dict[str, Any]] = []


# ============================================================================
# Reporting helpers
# ============================================================================


def _record_test(name: str, passed: bool, detail: str = "") -> None:
    TEST_RESULTS.append({"name": name, "passed": passed, "detail": detail})
    marker = "PASS" if passed else "FAIL"
    print(f"    [{marker}] {name}{f' — {detail}' if detail else ''}")


def _print_test_summary() -> None:
    _section("TEST SUMMARY")
    if not TEST_RESULTS:
        print("No test results were recorded.")
        return

    passed = sum(1 for r in TEST_RESULTS if r["passed"])
    failed = len(TEST_RESULTS) - passed
    print(f"Total: {len(TEST_RESULTS)} | PASS: {passed} | FAIL: {failed}")
    for i, result in enumerate(TEST_RESULTS, start=1):
        marker = "PASS" if result["passed"] else "FAIL"
        detail = result["detail"]
        print(f"{i:02d}. [{marker}] {result['name']}{f' — {detail}' if detail else ''}")


# ============================================================================
# HTTP helpers
# ============================================================================


def _url(path: str) -> str:
    return LELAMP_URL.rstrip("/") + path


def _check_file(rel: str) -> str:
    """Return absolute path to a mock-data WAV; fail-fast if missing."""
    p = MOCK_AUDIO_DIR / rel
    if not p.is_file():
        raise FileNotFoundError(f"mock audio file not found: {p}")
    return str(p)


def _req(method: str, path: str, **kwargs) -> dict[str, Any]:
    kwargs.setdefault("timeout", HTTP_TIMEOUT_S)
    resp = requests.request(method, _url(path), **kwargs)
    try:
        body = resp.json()
    except ValueError:
        body = {"_raw": resp.text}
    return {"status": resp.status_code, "body": body}


def _print(title: str, result: dict[str, Any]) -> None:
    """Pretty-print an HTTP outcome."""
    status = result["status"]
    marker = "OK " if 200 <= status < 300 else "ERR"
    print(f"\n[{marker} {status}] {title}")
    print(json.dumps(result["body"], indent=2, ensure_ascii=False))


def _section(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}")


# ============================================================================
# API wrappers — 1 function per endpoint
# ============================================================================


def api_health() -> dict[str, Any]:
    return _req("GET", "/health")


def api_list() -> dict[str, Any]:
    return _req("GET", "/speaker/list")


def api_enroll(
    name: str,
    wav_paths: list[str],
    *,
    telegram_username: str = "",
    telegram_id: str = "",
    origin: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "wav_paths": wav_paths}
    if telegram_username:
        payload["telegram_username"] = telegram_username
    if telegram_id:
        payload["telegram_id"] = telegram_id
    if origin:
        payload["origin"] = origin
    return _req("POST", "/speaker/enroll", json=payload)


def api_recognize(wav_path: str) -> dict[str, Any]:
    return _req("POST", "/speaker/recognize", json={"wav_path": wav_path})


def api_identity(
    name: str,
    *,
    telegram_username: str = "",
    telegram_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if telegram_username:
        payload["telegram_username"] = telegram_username
    if telegram_id:
        payload["telegram_id"] = telegram_id
    return _req("POST", "/speaker/identity", json=payload)


def api_remove(name: str) -> dict[str, Any]:
    return _req("POST", "/speaker/remove", json={"name": name})


def api_reset() -> dict[str, Any]:
    return _req("POST", "/speaker/reset")


# ============================================================================
# Scenario helpers — combine multiple calls into a named flow
# ============================================================================


def scenario_mic_enroll(name: str, samples_rel: list[str]) -> bool:
    """Simulate a user enrolling via mic (no Telegram identity)."""
    _section(f"Mic enroll — {name!r} with {len(samples_rel)} sample(s)")
    paths = [_check_file(s) for s in samples_rel]
    out = api_enroll(name, paths)
    _print(f"POST /speaker/enroll name={name}", out)
    return 200 <= out["status"] < 300


def scenario_telegram_enroll(
    name: str,
    samples_rel: list[str],
    *,
    tg_username: str,
    tg_id: str,
) -> bool:
    """Simulate a user enrolling from a Telegram voice note."""
    _section(
        f"Telegram enroll — {name!r} with tg_username={tg_username} tg_id={tg_id}"
    )
    paths = [_check_file(s) for s in samples_rel]
    out = api_enroll(
        name,
        paths,
        telegram_username=tg_username,
        telegram_id=tg_id,
    )
    _print(f"POST /speaker/enroll name={name} (telegram)", out)
    return 200 <= out["status"] < 300


def scenario_recognize(probe_rel: str, expect_name: str | None) -> bool:
    """Call /speaker/recognize and summarize whether it matched expectations."""
    _section(f"Recognize — probe={probe_rel} expect={expect_name!r}")
    path = _check_file(probe_rel)
    out = api_recognize(path)
    _print(f"POST /speaker/recognize wav={probe_rel}", out)

    body = out["body"]
    got = body.get("name")
    match = body.get("match")
    conf = body.get("confidence")
    if expect_name is None:
        passed = not match
        verdict = "PASS" if passed else "UNEXPECTED-MATCH"
    else:
        passed = bool(match and got == expect_name)
        verdict = "PASS" if passed else "MISMATCH"

    print(
        f"    → verdict={verdict}  got={got!r}  confidence={conf}  match={match}"
    )
    return passed


def scenario_two_turn_enroll_simulating_unknown_then_name() -> bool:
    """Simulate the mic 2-turn unknown -> intro flow."""
    _section("Two-turn enroll simulation — Darren introducing himself")
    # Turn A: unknown speaker (Darren but not yet enrolled).
    turn_a_audio = _check_file(DARREN_SAMPLES[0])
    out = api_recognize(turn_a_audio)
    _print("Turn A — POST /speaker/recognize (Darren, unenrolled)", out)

    unknown_path = out["body"].get("unknown_audio_path")
    if not unknown_path:
        print("    → NO unknown_audio_path returned; aborting 2-turn flow")
        return False

    print(f"    → captured unknown path: {unknown_path}")

    # Turn B: user says "I am Darren" — enroll with BOTH audio paths.
    turn_b_audio = _check_file(DARREN_SAMPLES[1])
    enroll_out = api_enroll("darren", [unknown_path, turn_b_audio])
    _print(
        "Turn B — POST /speaker/enroll with [Turn A unknown, Turn B name]",
        enroll_out,
    )
    return 200 <= enroll_out["status"] < 300


# ============================================================================
# Main orchestration
# ============================================================================


def main() -> int:
    print(f"LELAMP_URL = {LELAMP_URL}")
    print(f"MOCK_AUDIO_DIR = {MOCK_AUDIO_DIR}")

    # 0. Health.
    _section("0. Health")
    out = api_health()
    _print("GET /health", out)
    health_ok = out["status"] == 200
    _record_test("Health check", health_ok, f"status={out['status']}")
    if not health_ok:
        print("\n!! lelamp is not responding — start it first")
        _print_test_summary()
        return 1

    # 1. Optional reset so repeated runs are deterministic.
    if RESET_BEFORE_RUN:
        _section("1. Reset all voice profiles (clean slate)")
        out = api_reset()
        _print("POST /speaker/reset", out)
        _record_test("Reset voice profiles", 200 <= out["status"] < 300, f"status={out['status']}")

    # 2. List before any enrollment.
    _section("2. List (expected empty or just leftovers)")
    out = api_list()
    _print("GET /speaker/list", out)
    _record_test("List before enrollment", out["status"] == 200, f"status={out['status']}")

    # 3. Real-speaker test (requested): enroll Khanh_1,2 then recognize Khanh_3.
    _record_test(
        "Enroll Khanh with Khanh_1,2",
        scenario_mic_enroll(
            "khanh",
            ["Khanh/Khanh_1.wav", "Khanh/Khanh_2.wav"],
        ),
    )
    _record_test(
        "Real-speaker test Khanh_1,2 -> Khanh_3",
        scenario_recognize("Khanh/Khanh_3.wav", expect_name="khanh"),
    )

    # 4. Isolate next test by resetting profiles.
    _section("4. Reset for wrong-detect test isolation")
    out = api_reset()
    _print("POST /speaker/reset", out)
    _record_test(
        "Reset before wrong-detect test",
        200 <= out["status"] < 300,
        f"status={out['status']}",
    )

    # 5. Wrong-detect test (requested): enroll Khanh_2, test with Bao_2.
    _record_test(
        "Enroll Khanh with Khanh_2",
        scenario_mic_enroll("khanh", ["Khanh/Khanh_2.wav"]),
    )
    _record_test(
        "Wrong-detect test Khanh_2 vs Bao_2",
        scenario_recognize("Bao/Bao_2.wav", expect_name=None),
    )

    # 6. Reset again before running the original full regression flow.
    _section("6. Reset before full regression flow")
    out = api_reset()
    _print("POST /speaker/reset", out)
    _record_test(
        "Reset before full flow",
        200 <= out["status"] < 300,
        f"status={out['status']}",
    )

    # 7. Mic enroll — Darren with multiple samples.
    _record_test(
        "Mic enroll darren",
        scenario_mic_enroll("darren", DARREN_SAMPLES[:2]),
    )

    # 8. Telegram enroll — Khanh with telegram identity.
    _record_test(
        "Telegram enroll khanh",
        scenario_telegram_enroll(
            "khanh",
            KHANH_SAMPLES,
            tg_username=KHANH_TG_USERNAME,
            tg_id=KHANH_TG_ID,
        ),
    )

    # 9. Mic enroll — Bao (no telegram identity).
    _record_test("Mic enroll bao", scenario_mic_enroll("bao", BAO_SAMPLES))

    # 10. List — should now show 3 users with origins.
    _section("10. List after 3 enrolls")
    out = api_list()
    _print("GET /speaker/list", out)
    _record_test("List after 3 enrolls", out["status"] == 200, f"status={out['status']}")

    # 11. Recognize each known speaker with a different probe file.
    _record_test(
        "Recognize darren probe",
        scenario_recognize(DARREN_PROBE, expect_name="darren"),
    )
    _record_test(
        "Recognize khanh probe",
        scenario_recognize(KHANH_PROBE, expect_name="khanh"),
    )
    _record_test(
        "Recognize bao probe",
        scenario_recognize(BAO_PROBE, expect_name="bao"),
    )

    # 12. Re-enroll Darren with more samples (append).
    _section("12. Re-enroll Darren with 1 extra sample (append)")
    out = api_enroll("darren", [_check_file(DARREN_SAMPLES[2])])
    _print(
        f"POST /speaker/enroll name=darren (extra {DARREN_SAMPLES[2]})",
        out,
    )
    _record_test("Re-enroll darren append sample", 200 <= out["status"] < 300, f"status={out['status']}")

    # 13. Simulate the 2-turn unknown -> name flow.
    _record_test(
        "Two-turn enroll unknown->name flow",
        scenario_two_turn_enroll_simulating_unknown_then_name(),
    )

    # 14. Update identity on a mic-only user (Bao) — attach Telegram info.
    _section("14. Update identity — Bao gets Telegram linked")
    out = api_identity(
        "bao",
        telegram_username=BAO_TG_USERNAME,
        telegram_id=BAO_TG_ID,
    )
    _print("POST /speaker/identity name=bao", out)
    _record_test("Update identity for bao", 200 <= out["status"] < 300, f"status={out['status']}")

    # 15. Recognize Darren — inspect identity fields.
    _section("15. Recognize Darren (inspect identity fields in response)")
    out = api_recognize(_check_file(DARREN_PROBE))
    _print("POST /speaker/recognize Darren", out)
    _record_test("Recognize darren after identity updates", 200 <= out["status"] < 300, f"status={out['status']}")

    # 16. Remove one user (voice only — shared metadata preserved).
    _section("16. Remove khanh (voice only)")
    out = api_remove("khanh")
    _print("POST /speaker/remove name=khanh", out)
    _record_test("Remove khanh", 200 <= out["status"] < 300, f"status={out['status']}")

    # 17. List — should show 2 users remaining (darren, bao).
    _section("17. List after removing khanh")
    out = api_list()
    _print("GET /speaker/list", out)
    _record_test("List after removing khanh", out["status"] == 200, f"status={out['status']}")

    # 18. Error cases.
    _section("18. Error: enroll with non-existent file")
    out = api_enroll("ghost", ["/tmp/does-not-exist-12345.wav"])
    _print("POST /speaker/enroll (bad path)", out)
    _record_test("Error enroll with bad path", out["status"] >= 400, f"status={out['status']}")

    _section("19. Error: update identity on non-existent user")
    out = api_identity("nobody", telegram_id="0")
    _print("POST /speaker/identity name=nobody", out)
    _record_test("Error identity update for missing user", out["status"] >= 400, f"status={out['status']}")

    _section("20. Error: remove non-existent user")
    out = api_remove("ghost")
    _print("POST /speaker/remove name=ghost", out)
    _record_test("Error remove missing user", out["status"] >= 400, f"status={out['status']}")
    
    # 21. Final: list one more time.
    _section("21. Final list")
    out = api_list()
    _print("GET /speaker/list", out)
    _record_test("Final list", out["status"] == 200, f"status={out['status']}")

    _print_test_summary()
    print("\nAll scenarios executed. Review output above for details.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.ConnectionError as e:
        print(f"\n!! Cannot reach {LELAMP_URL}: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n!! Interrupted")
        sys.exit(130)