import os
import ccxt
import pandas as pd
import requests

# 取得環境變數
API_KEY = os.getenv('GATE_API_KEY')
API_SECRET = os.getenv('GATE_API_SECRET')
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 初始化交易所 (Gate.io)
exchange = ccxt.gateio({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap'  # 預設為永續合約 (Perpetual / Swap)
    }
})

def send_telegram(message):
    if TG_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram notification failed: {e}")

def fetch_data(symbol, timeframe, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def run_strategy():
    # Gate.io 在 CCXT 中的標準命名格式
    spot_symbol = 'BTC/USDT'          # 現貨
    futures_symbol = 'BTC/USDT:USDT'   # USDT 永續合約

    # 1. 抓取數據 (日線與小時線)
    df_spot_d = fetch_data(spot_symbol, '1d', limit=50)
    df_spot_h = fetch_data(spot_symbol, '1h', limit=5)
    df_futures_h = fetch_data(futures_symbol, '1h', limit=5)

    # 2. 計算 BIAS% (Daily Close vs Daily SMA20)
    daily_sma20 = df_spot_d['close'].rolling(window=20).mean()
    latest_daily_close = df_spot_d['close'].iloc[-1]
    latest_daily_sma20 = daily_sma20.iloc[-1]
    bias = ((latest_daily_close - latest_daily_sma20) / latest_daily_sma20) * 100

    # 3. 計算 Spread% ((Futures - Spot) / Spot * 100)
    latest_spot = df_spot_h['close'].iloc[-1]
    latest_futures = df_futures_h['close'].iloc[-1]
    spread_pct = ((latest_futures - latest_spot) / latest_spot) * 100

    print(f"Gate.io - BIAS%: {bias:.4f}%, Spread%: {spread_pct:.4f}%")

    # 4. 判斷交易條件
    long_condition = (bias < 0) and (spread_pct < 0)
    exit_condition = (bias > 0)

    # 取得當前合約持倉量
    positions = exchange.fetch_positions([futures_symbol])
    current_position = 0
    for p in positions:
        if p['symbol'] == futures_symbol:
            # CCXT 針對 Gate.io 回傳的 contracts 數量
            current_position = float(p['contracts']) if p['side'] == 'long' else 0

    # 5. 執行下單邏輯
    if long_condition:
        # Gate.io 永續合約最小下單單位 (依張數或幣數，請依實際市場規格調整)
        order_qty = 1  # 注意：部分 Gate.io 永續合約以「張 (contracts)」計算，1 張通常代表一定張數的 BTC
        order = exchange.create_market_buy_order(futures_symbol, order_qty)
        msg = f"🚀 [Gate.io H-Model] 觸發買入做多條件！\nBIAS: {bias:.2f}%\nSpread: {spread_pct:.4f}%\n成交單號: {order['id']}"
        print(msg)
        send_telegram(msg)

    elif exit_condition and current_position > 0:
        # 平掉多單 (Gate.io 合約平倉)
        order = exchange.create_market_sell_order(futures_symbol, current_position, params={'reduceOnly': True})
        msg = f"🔻 [Gate.io H-Model] 觸發平倉出場條件！\nBIAS: {bias:.2f}%\n平倉數量: {current_position}\n成交單號: {order['id']}"
        print(msg)
        send_telegram(msg)
    else:
        print("當前無交易訊號，維持現狀。")

if __name__ == '__main__':
    run_strategy()
