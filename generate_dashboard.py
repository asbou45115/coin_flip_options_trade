import os
import random
import datetime
import pandas as pd
import plotly.graph_objs as go

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionTradesRequest, StockLatestTradeRequest
from alpaca.data.enums import DataFeed

# === Load API keys from env vars or hardcoded ===
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "YOUR_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "YOUR_SECRET_KEY")

# === Alpaca Clients ===
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
options_data_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
stock_data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# === File Paths ===
CSV_PATH = "data/trades.csv"
HTML_OUTPUT = "docs/index.html"

def get_spy_price():
    try:
        trade_req = StockLatestTradeRequest(symbol_or_symbols="SPY")
        latest_trade = stock_data_client.get_stock_latest_trade(trade_req)
        return float(latest_trade["SPY"].price)
    except Exception as e:
        print(f"[ERROR] Failed to fetch SPY price: {e}")
        return None

def get_option_contracts(symbol, side, expiration_date):
    try:
        # Try multiple approaches to get SPY contracts
        print(f"[DEBUG] Requesting {side} contracts for {symbol} expiring {expiration_date}")
        
        request = GetOptionContractsRequest(
            underlying_symbol=symbol,  # Try without list first
            expiration_date=expiration_date,
            contract_type=side
        )
        response = trading_client.get_option_contracts(request)
        
        # Extract contracts from the response object
        contracts = response.option_contracts
        
        # Filter to only SPY contracts (in case API returns mixed results)
        spy_contracts = [c for c in contracts if c.underlying_symbol == symbol]
        
        print(f"[DEBUG] Total contracts returned: {len(contracts)}")
        print(f"[DEBUG] {symbol} contracts found: {len(spy_contracts)}")
        
        if contracts and not spy_contracts:
            print(f"[DEBUG] Sample returned contract underlying: {contracts[0].underlying_symbol}")
            print(f"[DEBUG] All underlying symbols: {set(c.underlying_symbol for c in contracts[:10])}")
        
        if spy_contracts:
            print(f"[DEBUG] Sample SPY contract: {spy_contracts[0].symbol} @ strike {spy_contracts[0].strike_price}")
            
        return spy_contracts  # Return only SPY contracts
    except Exception as e:
        print(f"[ERROR] Failed to fetch option contracts: {e}")
        # Try with list format as fallback
        try:
            print("[DEBUG] Trying with list format...")
            request = GetOptionContractsRequest(
                underlying_symbol=[symbol],
                expiration_date=expiration_date,
                contract_type=side
            )
            response = trading_client.get_option_contracts(request)
            contracts = response.option_contracts
            spy_contracts = [c for c in contracts if c.underlying_symbol == symbol]
            print(f"[DEBUG] Fallback attempt: found {len(spy_contracts)} SPY contracts")
            return spy_contracts
        except Exception as e2:
            print(f"[ERROR] Fallback also failed: {e2}")
            return []

def simulate_trade():
    today = datetime.date.today()
    side = random.choice(["call", "put"])
    print(f"[INFO] Flipped a coin: {side.upper()}")

    spy_price = get_spy_price()
    if spy_price is None:
        return None

    contracts = get_option_contracts("SPY", side, today)
    if not contracts:
        print("[WARN] No contracts returned.")
        return None

    # === Find nearest OTM contract ===
    otm_contracts = []
    
    print(f"[DEBUG] SPY price: {spy_price}, looking for {side} contracts")
    
    for c in contracts:
        try:
            strike = c.strike_price
            
            # Debug: Show a few contracts being evaluated
            if len(otm_contracts) < 3:
                print(f"[DEBUG] Evaluating contract: {c.symbol} strike={strike} vs SPY={spy_price}")
            
            # Filter for OTM contracts
            if (side == "call" and strike > spy_price) or (side == "put" and strike < spy_price):
                otm_contracts.append(c)
                if len(otm_contracts) <= 3:  # Show first few matches
                    print(f"[DEBUG] Added OTM contract: {c.symbol} @ {strike}")
                
        except Exception as e:
            print(f"[ERROR] Error processing contract {c}: {e}")
            continue
    
    print(f"[DEBUG] Found {len(otm_contracts)} OTM contracts")
    
    if not otm_contracts:
        print("[WARN] No OTM contracts found.")
        return None

    # Sort by distance from current price
    otm_contracts.sort(key=lambda c: abs(c.strike_price - spy_price))
    contract = otm_contracts[0]
    
    print(f"[INFO] Selected option: {contract.symbol} @ strike {contract.strike_price}")

    # === Get entry price via recent trade ===
    try:
        request = OptionTradesRequest(
            symbol_or_symbols=contract.symbol,  # Use symbol_or_symbols instead of symbol
            start=datetime.datetime.now() - datetime.timedelta(hours=1),
            end=datetime.datetime.now()
        )
        trades = options_data_client.get_option_trades(request).trades
        entry_price = float(trades[-1].price) if trades else 0
    except Exception as e:
        print(f"[ERROR] Failed to get entry price: {e}")
        entry_price = 0

    trade = {
        "date": str(today),
        "side": side,
        "symbol": contract.symbol,
        "strike": contract.strike_price,
        "expiry": str(contract.expiration_date),
        "entry_price": entry_price,
        "exit_price": None,
        "pnl": None
    }

    return trade

def close_trade(trade):
    try:
        request = OptionTradesRequest(
            symbol_or_symbols=trade["symbol"],  # Use symbol_or_symbols instead of symbol
            start=datetime.datetime.now() - datetime.timedelta(minutes=30),
            end=datetime.datetime.now()
        )
        trades = options_data_client.get_option_trades(request).trades
        close_price = float(trades[-1].price) if trades else 0
    except Exception as e:
        print(f"[ERROR] Failed to get exit price: {e}")
        close_price = 0

    trade["exit_price"] = close_price
    trade["pnl"] = round(close_price - trade["entry_price"], 2)
    print(f"[INFO] Closed trade: PnL = {trade['pnl']}")
    return trade

def update_trades():
    os.makedirs("data", exist_ok=True)
    try:
        df = pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        df = pd.DataFrame()

    if datetime.date.today().weekday() >= 5:
        print("[INFO] Weekend — no trade.")
        return df

    trade = simulate_trade()
    if not trade:
        print("[WARN] Trade simulation failed.")
        return df

    trade = close_trade(trade)
    df = pd.concat([df, pd.DataFrame([trade])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)
    return df

def generate_plot(df):
    os.makedirs("docs", exist_ok=True)

    if df.empty or "pnl" not in df.columns:
        print("[WARN] No valid data to plot.")
        return

    df["cumulative_pnl"] = df["pnl"].cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["cumulative_pnl"],
        mode="lines+markers",
        name="Cumulative PnL"
    ))

    fig.update_layout(
        title="Coin Flip Options Strategy on SPY",
        xaxis_title="Date",
        yaxis_title="Cumulative PnL ($)",
        template="plotly_white"
    )

    fig.write_html(HTML_OUTPUT)
    print(f"[SUCCESS] Dashboard written to {HTML_OUTPUT}")

if __name__ == "__main__":
    df = update_trades()
    generate_plot(df)