# ledger.py - records trades, fees, P&L, delta penalty accrual
import pandas as pd
import time
from typing import Dict, Any

COMMISSION_OPTION = 1.0  # $1 per contract
COMMISSION_ETF = 0.01    # $0.01 per share

class Ledger:
    def __init__(self):
        self.rows = []
        self.start_time = time.time()
        self.cumulative_commissions = 0.0
        self.cumulative_penalties = 0.0
        self.realized_pnl = 0.0

    def record_order(self, order: Dict[str,Any], side_commission:float):
        # order is API response; store basics
        entry = {
            'timestamp': time.time(),
            'order': order,
            'commission': side_commission
        }
        self.cumulative_commissions += side_commission
        self.rows.append(entry)

    def record_penalty(self, penalty: float, tick:int):
        self.cumulative_penalties += penalty
        self.rows.append({'timestamp': time.time(), 'penalty': penalty, 'tick': tick})

    def add_realized_pnl(self, pnl: float):
        self.realized_pnl += pnl

    def export(self, filename='ledger.csv'):
        df = pd.DataFrame(self.rows)
        df.to_csv(filename, index=False)
        return filename

    def summary(self):
        return {
            'commissions': self.cumulative_commissions,
            'penalties': self.cumulative_penalties,
            'realized_pnl': self.realized_pnl,
            'rows': len(self.rows)
        }
