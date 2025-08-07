import os
import random
import datetime
import pandas as pd
import plotly.graph_objs as go
from alpaca.trading.client import TradingClient
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionTradesRequest

# Load API keys from env (in GitHub Actions use Secrets)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# Alpaca clients
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
data_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

CSV_PATH = 'data/trades.csv'
HTML_OUTPUT = 'docs/index.html'

def simulate_trade():
    today = datetime.date.today()
    side = random.choice(["call", "put"])
    
    # Get SPY price
    spy_quote = trading_client.get_last_trade("SPY")
    spy_price = float(spy_quote.price)

    # Fetch options chain for SPY expiring today
    contracts = trading_client.get_option_chain(
        symbol="SPY",
        expiration=today,
        type=side,
    )

    if not contracts:
        print("No contracts found.")
        return None

    # Filter for nearest OTM
    otm_contracts = [c for c in contracts if
                     (c.strike > spy_price if side == "call" else c.strike < spy_price)]
    if not otm_contracts:
        print("No OTM contracts.")
        return None

    contract = otm_contracts[0]
    entry_price = float(contract.ask_price or contract.mark_price or 0)

    trade = {
        'date': str(today),
        'side': side,
        'symbol': contract.symbol,
        'strike': contract.strike,
        'expiry': contract.expiration_date,
        'entry_price': entry_price,
        'exit_price': None,
        'pnl': None
    }

    return trade

def close_trade(trade):
    try:
        request = OptionTradesRequest(
            symbol=trade['symbol'],
            start=datetime.datetime.now() - datetime.timedelta(hours=8),
            end=datetime.datetime.now()
        )
        trades = data_client.get_option_trades(request).trades
        close_price = trades[-1].price if trades else 0
    except Exception as e:
        print(f"Error fetching close price: {e}")
        close_price = 0

    trade['exit_price'] = close_price
    trade['pnl'] = close_price - trade['entry_price']
    return trade

def update_trades():
    os.makedirs("data", exist_ok=True)
    try:
        df = pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        df = pd.DataFrame()

    # Skip weekends
    if datetime.date.today().weekday() >= 5:
        print("Weekend: no trade.")
        return df

    trade = simulate_trade()
    if not trade:
        return df

    trade = close_trade(trade)

    df = pd.concat([df, pd.DataFrame([trade])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)
    return df

def generate_plot(df):
    os.makedirs("docs", exist_ok=True)

    df['cumulative_pnl'] = df['pnl'].cumsum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['date'],
        y=df['cumulative_pnl'],
        mode='lines+markers',
        name='Cumulative PnL'
    ))

    fig.update_layout(
        title="Random Option Trading Strategy (Coin Flip)",
        xaxis_title="Date",
        yaxis_title="Cumulative PnL ($)",
        template="plotly_white"
    )

    fig.write_html(HTML_OUTPUT)
    print(f"Dashboard updated → {HTML_OUTPUT}")

if __name__ == "__main__":
    df = update_trades()
    generate_plot(df)
