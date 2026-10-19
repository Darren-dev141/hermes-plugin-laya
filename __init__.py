"""hermes-plugin-laya: Laya decision tools, native in Hermes.

Registers five tools that call the local Laya decision server over HTTP —
no shelling out to a CLI:

  * laya_health — is the server up and warm?
  * laya_choose — pick the best of <=10 options for a situation
  * laya_yes_no — one yes/no question, returns P(yes)
  * laya_rank   — rank <=10 candidates best-first
  * laya_judge  — one choice + typed yes_no/score fields in a single pass

"Jev" means Laya here: these are Laya's tools, served by the Laya running
on this machine (loopback-only by design — see README before even thinking
about pointing LAYA_URL anywhere public). Every result carries the
decision_id under which Laya logged the call.
"""

from __future__ import annotations

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    client = tools.build_client(ctx)
    logger.info("hermes-plugin-laya: Laya at %s", client.base_url)
    ctx.register_tool(
        name="laya_health", toolset="laya",
        schema=schemas.HEALTH, handler=tools.make_health(client),
    )
    ctx.register_tool(
        name="laya_choose", toolset="laya",
        schema=schemas.CHOOSE, handler=tools.make_choose(client),
    )
    ctx.register_tool(
        name="laya_yes_no", toolset="laya",
        schema=schemas.YES_NO, handler=tools.make_yes_no(client),
    )
    ctx.register_tool(
        name="laya_rank", toolset="laya",
        schema=schemas.RANK, handler=tools.make_rank(client),
    )
    ctx.register_tool(
        name="laya_judge", toolset="laya",
        schema=schemas.JUDGE, handler=tools.make_judge(client),
    )
