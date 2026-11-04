"""주간 모의 실행 CLI. 실채널 게시 기능은 없다 (mock: 계정만)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .store import Store
from .workflow import MockChannelAdapter, recover_stale_claims, run_week

CHANNELS = ("smartstore", "danggeun", "bunjang")


def week_key(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now(ZoneInfo("Asia/Seoul"))).isocalendar()
    return f"{y}-W{w:02d}"


def main(argv: list[str]) -> int:
    if argv[:1] != ["weekly-mock"]:
        print("usage: python -m app.purchasing.cli weekly-mock", file=sys.stderr)
        return 2
    store = Store(os.environ.get("PURCHASING_DB", "purchasing.db"))
    adapter = MockChannelAdapter(store)
    recover_stale_claims(store, adapter)
    with store.tx() as c:
        rows = c.execute("SELECT DISTINCT product_id, channel, account FROM approvals WHERE revoked_at IS NULL AND account LIKE 'mock:%'").fetchall()
    summary = run_week(store, week_key(), [(r[0], r[1], r[2]) for r in rows], adapter)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
