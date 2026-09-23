"""
Single-shot NSE scanner runner.

Scheduled execution:
09:46-09:55 IST

Manual execution:
Allowed for testing.

The runner:
1. verifies weekday
2. verifies execution window for scheduled runs
3. allows manual runs for testing
4. runs scanner.run_live_scan() exactly once
5. exits
"""

from **future** import annotations

import os
import sys

import pandas as pd

from scanner import (
EXECUTION_TIME,
MARKET_TZ,
run_live_scan,
)

def main() -> int:

```
now = pd.Timestamp.now(
    tz=MARKET_TZ
)

event_name = os.getenv(
    "GITHUB_EVENT_NAME",
    ""
)

is_manual = (
    event_name == "workflow_dispatch"
)

print(
    f"Runner time: "
    f"{now:%Y-%m-%d %H:%M:%S %Z}"
)

print(
    f"GitHub event: "
    f"{event_name or 'local execution'}"
)

# ------------------------------------------------------------
# Monday-Friday only.
# ------------------------------------------------------------

if now.weekday() >= 5:

    print(
        "Weekend. Scanner will not execute."
    )

    return 0

# ------------------------------------------------------------
# Manual GitHub Action execution.
#
# This bypasses the 09:46-09:55 time gate so the workflow
# can be tested manually.
#
# IMPORTANT:
# A manual run outside market hours is NOT a true live
# 09:45 signal. It is only a pipeline/data/Telegram test.
# ------------------------------------------------------------

if is_manual:

    print(
        "Manual workflow execution detected."
    )

    print(
        "Time-window restriction bypassed "
        "for testing."
    )

else:

    # --------------------------------------------------------
    # Scheduled execution window.
    # --------------------------------------------------------

    execution_start = pd.Timestamp(
        f"{now:%Y-%m-%d} 09:46:00",
        tz=MARKET_TZ,
    )

    execution_end = pd.Timestamp(
        f"{now:%Y-%m-%d} 09:55:00",
        tz=MARKET_TZ,
    )

    if not (
        execution_start
        <= now
        <= execution_end
    ):

        print(
            "Outside live execution window."
        )

        print(
            "Expected: "
            "09:46-09:55 IST"
        )

        return 0

# ------------------------------------------------------------
# Execute scanner exactly once.
# ------------------------------------------------------------

print(
    "Executing ONE scanner run..."
)

try:

    run_live_scan()

except Exception as exc:

    print(
        f"Scanner failed: "
        f"{type(exc).__name__}: {exc}"
    )

    return 1

print(
    "Scanner completed successfully."
)

return 0
```

if **name** == "**main**":

```
sys.exit(
    main()
)
```
