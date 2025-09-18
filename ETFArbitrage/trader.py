# trader.py
import time
import logging
from rit_client import RITClient
from strategy import StrategyEngine
from executor import Executor
from config import ETF_TICKER, BULL_TICKER, BEAR_TICKER, FX_TICKER, SLEEP_BETWEEN_CYCLES, MAX_GROSS_LIMIT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def compute_inventory_gross(securities):
    gross = 0
    for s in securities:
        pos = s.get("position", 0)
        mult = 2 if s.get("ticker") == ETF_TICKER else 1
        gross += abs(pos) * mult
    return gross

def main_loop():
    client = RITClient('IIFLZKL1')
    strategy = StrategyEngine(client)
    execu = Executor(client)
    logging.info("Starting RIT trader main loop. Press Ctrl+C to stop.")
    MAX_GROSS_LIMIT = client.get_limits()[0]['gross_limit']
#    print(client.get_limits())
    while True:
        try:
            # 1) fetch tenders
            tenders = client.get_tenders() or []
            quotes = strategy.fetch_quotes()

            # check gross limit before accepting
            securities = client.get_securities()  # list of dicts
            gross = compute_inventory_gross(securities)
            logging.debug("Gross inventory units: %s", gross)

            for t in tenders:
                tid = t.get("tender_id")
                logging.info("Found tender id=%s price=%s qty=%s", tid, t.get("price"), t.get("quantity"))

                evalr = strategy.evaluate_tender(t, quotes)
                logging.info("Tender eval: %s | reason: %s", evalr["decision"], evalr["reason"])

                if evalr["decision"] == "ACCEPT":
                    # double-check limits
                    if gross + abs(t.get("quantity")) * 2 > MAX_GROSS_LIMIT:
                        logging.warning("Skipping tender %s: would breach gross limit", tid)
                        client.decline_tender(tid)
                        continue
                    logging.info("Accepting tender %s", tid)
                    accept_resp = client.accept_tender(tid)
                    logging.info("Tender accepted response: %s", accept_resp)

                    # unwind: if we've accepted ETF tender, we likely received ETF shares (long/short depending)
                    # We'll assume tender gave us long ETF that we should convert/sell
                    # Choose cheapest unwind: try converter via leases if available and big size, else slice sell ETF
                    qty = t.get("quantity", 0)
                    # Simple heuristic: if qty >= 10000 and converter available -> use converter
                    if qty >= 10000:
                        logging.info("Large tender: trying converter path (requires lease usage implementation)")
                        # Here you'd use client.get_leases() and client.use_lease(...) based on available Converters
                        # For now, fallback to slicing sell ETF
                        orders = execu.slice_and_execute(ETF_TICKER, "SELL", qty)
                    else:
                        # immediate slicing sell of ETF at NBBO limit orders (passive)
                        book = client.get_security_book(ETF_TICKER)
                        orders = execu.slice_and_execute(ETF_TICKER, "SELL", qty, side_book=book, aggressive=False)
                    logging.info("Unwind orders submitted: %s", orders)

                    # update gross
                    securities = client.get_securities()
                    gross = compute_inventory_gross(securities)

                elif evalr["decision"] == "DECLINE":
                    logging.info("Declining tender %s per strategy", tid)
                    client.decline_tender(tid)
                else:
                    logging.debug("Holding on tender %s", tid)
            time.sleep(SLEEP_BETWEEN_CYCLES)
        except KeyboardInterrupt:
            logging.info("Stopping trader.")
            break
        except Exception as e:
            logging.exception("Error in main loop: %s", e)
            time.sleep(1.0)

if __name__ == "__main__":
    main_loop()
