# trader.py
import time
import logging
from rit_client import RITClient
from strategy import StrategyEngine
from executor import Executor
from config import (
    ETF_TICKER, BULL_TICKER, BEAR_TICKER,
    SLEEP_BETWEEN_CYCLES, MAX_GROSS_LIMIT, CONVERTER_BATCH,
    ENABLE_SPOT_ARB, SPOT_ARB_ETF_CLIP, SPOT_ARB_STOCK_CLIP, SPOT_ARB_COOLDOWN_S
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def compute_inventory_gross(securities):
    gross = 0
    for s in securities:
        pos = int(s.get("position", 0))
        mult = 2 if s.get("ticker") == ETF_TICKER else 1
        gross += abs(pos) * mult
    return gross

def flatten_after_converter(execu: Executor, conv_type: str, blocks: int):
    """
    After converter use, neutralize inventory.
    Redemption => long basket + short ETF: SELL basket, BUY ETF
    Creation   => long ETF + short basket: SELL ETF, BUY basket
    """
    size = blocks * CONVERTER_BATCH
    if size <= 0:
        return
    if conv_type == "ETF-Redemption":
        logging.info("Flattening after Redemption: SELL BULL/BEAR, BUY ETF")
        execu.slice_and_execute(BULL_TICKER, "SELL", size)
        execu.slice_and_execute(BEAR_TICKER, "SELL", size)
        execu.slice_and_execute(ETF_TICKER,  "BUY",  size)
    else:
        logging.info("Flattening after Creation: SELL ETF, BUY BULL/BEAR")
        execu.slice_and_execute(ETF_TICKER,  "SELL", size)
        execu.slice_and_execute(BULL_TICKER, "BUY",  size)
        execu.slice_and_execute(BEAR_TICKER, "BUY",  size)

def main_loop():
    client   = RITClient()
    strategy = StrategyEngine(client)
    execu    = Executor(client)

    logging.info("Starting ETF Arbitrage Trader. Ctrl+C to stop.")

    # derive gross limit if available
    try:
        lims = client.get_limits()
        gross_limit = lims[0]["gross_limit"] if lims else MAX_GROSS_LIMIT
    except Exception:
        gross_limit = MAX_GROSS_LIMIT

    while True:
        try:
            quotes = strategy.fetch_quotes()
            tenders = client.get_tenders() or []
            securities = client.get_securities()
            gross = compute_inventory_gross(securities)

            # ---------- Tenders ----------
            for t in tenders:
                tid = int(t.get("tender_id", t.get("id", -1)))
                qty = int(t.get("quantity", 0))
                logging.info(f"Tender id={tid} price={t.get('price')} qty={qty}")

                evalr = strategy.evaluate_tender(t, quotes)
                logging.info(f"Tender eval: {evalr['decision']} | {evalr['reason']}")

                if evalr["decision"] != "ACCEPT":
                    client.decline_tender(tid)
                    logging.info(f"Declined tender {tid}")
                    continue

                # limit guard
                projected_gross = gross + abs(qty) * 2
                if projected_gross > gross_limit:
                    logging.warning(f"Skip tender {tid}: would breach gross ({projected_gross}>{gross_limit})")
                    client.decline_tender(tid)
                    continue

                # Accept
                resp = client.accept_tender(tid)
                logging.info(f"Accepted tender {tid}: {resp}")

                # Unwind: choose converter for big blocks, then flatten immediately
                blocks   = abs(qty) // CONVERTER_BATCH
                leftover = abs(qty) %  CONVERTER_BATCH
                conv_type = "ETF-Redemption" if evalr["side"] == "SELL" else "ETF-Creation"

                if blocks > 0:
                    logging.info(f"Using converter {conv_type} x {blocks}")
                    conv_resp = execu.use_converter(conv_type)
                    logging.info(f"Converter response: {conv_resp}")
                    flatten_after_converter(execu, conv_type, blocks)

                # Leftover via ETF market
                if leftover > 0:
                    side = "SELL" if evalr["side"] == "SELL" else "BUY"
                    book = client.get_security_book(ETF_TICKER)
                    orders = execu.slice_and_execute(ETF_TICKER, side, leftover, side_book=book, aggressive=False)
                    logging.info(f"Unwind leftover orders: {orders}")

                # refresh gross
                securities = client.get_securities()
                gross = compute_inventory_gross(securities)

            # ---------- Continuous spot arbitrage ----------
            if ENABLE_SPOT_ARB:
                spot = strategy.check_spot_arbitrage(quotes)
                if spot["decision"] == "BUY_ETF_SELL_BASKET":
                    logging.info(f"[Spot] BUY ETF / SELL basket | {spot['reason']}")
                    execu.slice_and_execute(ETF_TICKER,  "BUY",  SPOT_ARB_ETF_CLIP)
                    execu.slice_and_execute(BULL_TICKER, "SELL", SPOT_ARB_STOCK_CLIP)
                    execu.slice_and_execute(BEAR_TICKER, "SELL", SPOT_ARB_STOCK_CLIP)
                    time.sleep(SPOT_ARB_COOLDOWN_S)
                elif spot["decision"] == "SELL_ETF_BUY_BASKET":
                    logging.info(f"[Spot] SELL ETF / BUY basket | {spot['reason']}")
                    execu.slice_and_execute(ETF_TICKER,  "SELL", SPOT_ARB_ETF_CLIP)
                    execu.slice_and_execute(BULL_TICKER, "BUY",  SPOT_ARB_STOCK_CLIP)
                    execu.slice_and_execute(BEAR_TICKER, "BUY",  SPOT_ARB_STOCK_CLIP)
                    time.sleep(SPOT_ARB_COOLDOWN_S)
                else:
                    logging.debug(f"[Spot] {spot['reason']}")

            time.sleep(SLEEP_BETWEEN_CYCLES)

        except KeyboardInterrupt:
            logging.info("Stopping trader.")
            break
        except Exception as e:
            logging.exception(f"Error in main loop: {e}")
            time.sleep(1.0)

if __name__ == "__main__":
    main_loop()
