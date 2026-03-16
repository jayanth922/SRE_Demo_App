#!/usr/bin/env python3
"""
Load Generator — continuously fires traffic at the demo services.

Simulates realistic user behavior:
  - Mix of checkout and inventory requests
  - Burst mode every ~60s to spike error rates
  - Random order IDs to vary logs
"""

import asyncio
import json
import logging
import os
import random
import string
import time
import httpx

# ── Config ──────────────────────────────────────────────────────────────────
GATEWAY_URL     = os.getenv("GATEWAY_URL",      "http://api-gateway:8000")
RPS             = float(os.getenv("RPS",         "5"))    # requests per second
BURST_RPS       = float(os.getenv("BURST_RPS",  "20"))   # burst rate
BURST_DURATION  = int(os.getenv("BURST_DURATION", "15")) # seconds
BURST_INTERVAL  = int(os.getenv("BURST_INTERVAL", "60")) # seconds between bursts

logging.basicConfig(
    level=logging.INFO,
    format=json.dumps({
        "timestamp": "%(asctime)s", "level": "%(levelname)s",
        "service": "load-generator", "message": "%(message)s"
    })
)
logger = logging.getLogger("load-gen")

ITEM_IDS = ["item-001", "item-002", "item-003", "item-004", "item-005", "item-999"]  # 999 = 404

def random_order_id() -> str:
    return "ord-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

async def checkout(client: httpx.AsyncClient):
    order_id = random_order_id()
    try:
        resp = await client.post(f"{GATEWAY_URL}/checkout/{order_id}", timeout=6.0)
        status = resp.status_code
        if status >= 500:
            logger.warning(f"Checkout failed order={order_id} status={status}")
        else:
            logger.info(f"Checkout ok order={order_id} status={status}")
    except Exception as e:
        logger.error(f"Checkout error order={order_id} error={e}")

async def inventory_list(client: httpx.AsyncClient):
    try:
        resp = await client.get(f"{GATEWAY_URL}/inventory", timeout=6.0)
        logger.info(f"Inventory list status={resp.status_code}")
    except Exception as e:
        logger.error(f"Inventory list error={e}")

async def inventory_item(client: httpx.AsyncClient):
    item_id = random.choice(ITEM_IDS)
    try:
        resp = await client.get(f"{GATEWAY_URL}/inventory/{item_id}", timeout=6.0)
        if resp.status_code == 404:
            logger.warning(f"Inventory 404 item={item_id}")
        else:
            logger.info(f"Inventory item ok item={item_id} status={resp.status_code}")
    except Exception as e:
        logger.error(f"Inventory item error item={item_id} error={e}")

async def reindex(client: httpx.AsyncClient):
    """Trigger CPU spike on inventory service."""
    try:
        await client.post(f"{GATEWAY_URL.replace('8000', '8002')}/reindex", timeout=10.0)
        logger.info("Reindex triggered")
    except Exception:
        pass

async def run_request(client: httpx.AsyncClient):
    """Pick a request type with weighted probability."""
    roll = random.random()
    if roll < 0.45:
        await checkout(client)
    elif roll < 0.75:
        await inventory_list(client)
    elif roll < 0.95:
        await inventory_item(client)
    else:
        await reindex(client)

async def main():
    logger.info(f"Load generator starting — target={GATEWAY_URL} rps={RPS} burst_rps={BURST_RPS}")

    # Wait for services to be ready
    await asyncio.sleep(5)

    burst_active   = False
    last_burst_end = 0.0

    async with httpx.AsyncClient() as client:
        while True:
            now = time.time()

            # Toggle burst mode
            if not burst_active and (now - last_burst_end) >= BURST_INTERVAL:
                burst_active = True
                burst_end    = now + BURST_DURATION
                logger.warning(f"Burst mode ON for {BURST_DURATION}s at {BURST_RPS} rps")
            elif burst_active and now >= burst_end:
                burst_active   = False
                last_burst_end = now
                logger.info("Burst mode OFF")

            current_rps = BURST_RPS if burst_active else RPS
            tasks = [run_request(client) for _ in range(int(current_rps))]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(main())
