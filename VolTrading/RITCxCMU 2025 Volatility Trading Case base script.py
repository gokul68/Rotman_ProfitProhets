"""
RIT Market Simulator Volatility Trading Case - Support File
Rotman BMO Finance Research and Trading Lab, Uniersity of Toronto (C)
All rights reserved.
"""
import warnings
import signal
import requests
from time import sleep
import pandas as pd
import numpy as np
#black scholes libraries
from py_vollib.black_scholes import black_scholes as bs
from py_vollib.black_scholes.greeks.analytical import delta
import py_vollib.black.implied_volatility as iv
"""
To install py_vollib, use conda install jholdom::py_vollib, since it requires Python versions between 3.6 and 3.8.
If that doesn’t work, try:
    conda install anaconda::pip
    pip install py_vollib
"""

# Define variables 
# risk free rate r
# Stock price s
# strike price k
# time remaining (in years)

#ESTIMATE YOUR VOLATILITY:
vol = 0.25

#class that passes error message, ends the program
class ApiException(Exception):
    pass

#code that lets us shut down if CTRL C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True
    
API_KEY = {'X-API-Key': 'IIFLZKL1'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)
    
#code that gets the current tick
def get_tick(session):
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        return case['tick']
    raise ApiException('fail - cannot get tick')

#code that gets the securities via json  
def get_s(session):
    price_act = session.get('http://localhost:9999/v1/securities')
    if price_act.ok:
        prices = price_act.json()
        return prices
    raise ApiException('fail - cannot get securities')

def years_r(mat, tick):
    yr = (mat - tick)/3600 
    return yr
    
def main():
    with requests.Session() as session:
        session.headers.update(API_KEY)
        while get_tick(session) < 300 and not shutdown:
            assets = pd.DataFrame(get_s(session))
            assets2 = assets.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
            helper = pd.DataFrame(index = range(1),columns = ['share_exposure', 'required_hedge', 'must_be_traded', 'current_pos', 'required_pos', 'SAME?'])
            assets2['delta'] = np.nan
            assets2['i_vol'] = np.nan
            assets2['bsprice'] = np.nan
            assets2['diffcom'] = np.nan
            assets2['abs_val'] = np.nan
            assets2['decision'] = np.nan
            assets2
            
            for row in assets2.index.values:
                if 'P' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'PUT'
                    market_price = assets2['last'].iloc[row]
                    
                    if get_tick(session) < 300:
                        assets2['delta'].iloc[row] = delta('p', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        assets2['bsprice'].iloc[row] = bs('p', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        
                        # Compute intrinsic make sure the volatility is not below the intrinsic value.
                        try:
                            assets2['i_vol'].iloc[row] = iv.implied_volatility(assets2['last'].iloc[row], assets2['last'].iloc[0],
                                                                      float(assets2['ticker'].iloc[row][3:5]), 0, years_r(300, get_tick(session)),
                                                                      'p')
                        except Exception as e:
                            print(f"Implied volatility error {e}")
                            assets2['i_vol'].iloc[row] = np.nan
                        
                elif 'C' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'CALL'
                    if get_tick(session) < 300:
                        assets2['delta'].iloc[row] = delta('c', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        assets2['bsprice'].iloc[row] = bs('c', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        
                        # intrinsic = max(float(assets2['ticker'].iloc[row][3:5]) - assets2['last'].iloc[0], 0)
                        # if assets2['last'].iloc[row] < intrinsic:
                        #     assets2['i_vol'].iloc[row] = np.nan  # or a default/estimated vol
                        # else:
                        try:
                            assets2['i_vol'].iloc[row] = iv.implied_volatility(assets2['last'].iloc[row], assets2['last'].iloc[0],
                                                                      float(assets2['ticker'].iloc[row][3:5]), 0, years_r(300, get_tick(session)),
                                                                      'c')
                        except Exception as e:
                            print(f"Implied volatility error {e}")
                            assets2['i_vol'].iloc[row] = np.nan
                        
                if assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] > 0:
                    assets2['diffcom'].iloc[row] = assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] - 0.02
                    assets2['abs_val'].iloc[row] = abs(assets2['diffcom'].iloc[row])
                elif assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] < 0:
                    assets2['diffcom'].iloc[row] = assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] + 0.02
                    assets2['abs_val'].iloc[row] = abs(assets2['diffcom'].iloc[row])
                if assets2['diffcom'].iloc[row] > 0.02:
                    assets2['decision'].iloc[row] = 'SELL'
                elif assets2['diffcom'].iloc[row] < -0.02:
                    assets2['decision'].iloc[row] = 'BUY'
                else:
                    assets2['decision'].iloc[row] = 'NO DECISION'
                warnings.filterwarnings('ignore')
                
            a1 = np.array(assets2['position'].iloc[1:])
            a2 = np.array(assets2['size'].iloc[1:])
            a3 = np.array(assets2['delta'].iloc[1:])
            
            helper['share_exposure'] = np.nansum(a1 * a2 * a3)
            helper['required_hedge'] = helper['share_exposure'].iloc[0] * -1
            helper['must_be_traded'] = helper['required_hedge']/assets2['position'].iloc[0] - assets2['position'].iloc[0]
            if assets2['position'].iloc[0] > 0:
                helper['current_pos'] = 'LONG'
            elif assets2['position'].iloc[0] < 0:
                helper['current_pos'] = 'SHORT'
            else:
                helper['current_pos'] = 'NO POSITION'
            if helper['required_hedge'].iloc[0] > 0:
                helper['required_pos'] = 'LONG'
            elif helper['required_hedge'].iloc[0] < 0:
                helper['required_pos'] = 'SHORT'
            else:
                helper['required_pos'] = 'NO POSITION'
            helper['SAME?'] = (helper['required_pos'] == helper['current_pos'])
            print(assets2.to_markdown(), end='\n'*2)
            print(helper.to_markdown(), end='\n'*2)
            
            # import matplotlib.pyplot as plt
            # y = assets2['last']
            # plt.plot(y)
            # plt.plotsize(50, 30)
            sleep(0.5)
if __name__ == '__main__':
    with requests.Session() as session:
        session.headers.update(API_KEY)
        while get_tick(session) < 300 and not shutdown:
            assets = pd.DataFrame(get_s(session))
            assets2 = assets.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
            helper = pd.DataFrame(index = range(1),columns = ['share_exposure', 'required_hedge', 'must_be_traded', 'current_pos', 'required_pos', 'SAME?'])
            assets2['delta'] = np.nan
            assets2['i_vol'] = np.nan
            assets2['bsprice'] = np.nan
            assets2['diffcom'] = np.nan
            assets2['abs_val'] = np.nan
            assets2['decision'] = np.nan
            assets2
            
            for row in assets2.index.values:
                if 'P' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'PUT'
                    intrinsic = max(assets2['last'].iloc[0] - float(assets2['ticker'].iloc[row][3:5]),0)
                    market_price = assets2['last'].iloc[row]
                    
                    if get_tick(session) < 300:
                        assets2['delta'].iloc[row] = delta('p', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        assets2['bsprice'].iloc[row] = bs('p', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        
                        try:
                            assets2['i_vol'].iloc[row] = iv.implied_volatility(assets2['last'].iloc[row], assets2['last'].iloc[0],
                                                                      float(assets2['ticker'].iloc[row][3:5]), 0, years_r(300, get_tick(session)),
                                                                      'p')
                        except Exception as e:
                            print(f"Implied volatility error {e}")
                            assets2['i_vol'].iloc[row] = np.nan
                        
                elif 'C' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'CALL'
                    if get_tick(session) < 300:
                        assets2['delta'].iloc[row] = delta('c', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        assets2['bsprice'].iloc[row] = bs('c', assets2['last'].iloc[0], float(assets2['ticker'].iloc[row][3:5]), 
                                                           years_r(300, get_tick(session)), 0, vol)
                        
                        try:
                            assets2['i_vol'].iloc[row] = iv.implied_volatility(assets2['last'].iloc[row], assets2['last'].iloc[0],
                                                                      float(assets2['ticker'].iloc[row][3:5]), 0, years_r(300, get_tick(session)),
                                                                      'c')
                        except Exception as e:
                            print(f"Implied volatility error {e}")
                            assets2['i_vol'].iloc[row] = np.nan
                            
                if assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] > 0:
                    assets2['diffcom'].iloc[row] = assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] - 0.02
                    assets2['abs_val'].iloc[row] = abs(assets2['diffcom'].iloc[row])
                elif assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] < 0:
                    assets2['diffcom'].iloc[row] = assets2['last'].iloc[row] - assets2['bsprice'].iloc[row] + 0.02
                    assets2['abs_val'].iloc[row] = abs(assets2['diffcom'].iloc[row])
                if assets2['diffcom'].iloc[row] > 0.02:
                    assets2['decision'].iloc[row] = 'SELL'
                elif assets2['diffcom'].iloc[row] < -0.02:
                    assets2['decision'].iloc[row] = 'BUY'
                else:
                    assets2['decision'].iloc[row] = 'NO DECISION'
                warnings.filterwarnings('ignore')
                
            a1 = np.array(assets2['position'].iloc[1:])
            a2 = np.array(assets2['size'].iloc[1:])
            a3 = np.array(assets2['delta'].iloc[1:])
            
            helper['share_exposure'] = np.nansum(a1 * a2 * a3)
            helper['required_hedge'] = helper['share_exposure'].iloc[0] * -1
            helper['must_be_traded'] = helper['required_hedge']/assets2['position'].iloc[0] - assets2['position'].iloc[0]
            if assets2['position'].iloc[0] > 0:
                helper['current_pos'] = 'LONG'
            elif assets2['position'].iloc[0] < 0:
                helper['current_pos'] = 'SHORT'
            else:
                helper['current_pos'] = 'NO POSITION'
            if helper['required_hedge'].iloc[0] > 0:
                helper['required_pos'] = 'LONG'
            elif helper['required_hedge'].iloc[0] < 0:
                helper['required_pos'] = 'SHORT'
            else:
                helper['required_pos'] = 'NO POSITION'
            helper['SAME?'] = (helper['required_pos'] == helper['current_pos'])
            print(assets2.to_markdown(), end='\n'*2)
            print(helper.to_markdown(), end='\n'*2)
            
    
