from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import json
import uuid
import gzip
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.txt')
TG_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telegram_config.txt')
TRADES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.json')
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist.json')
INSTRUMENTS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instruments_nse_eq.json')
FO_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instruments_nse_fo.json')
INSTRUMENTS_URL = 'https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz'

def get_token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()

def get_telegram_config():
    with open(TG_CONFIG_FILE) as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
        return lines[0], lines[1]

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE) as f:
        return json.load(f)

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=2)

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE) as f:
        return json.load(f)

def save_watchlist(items):
    with open(WATCHLIST_FILE, 'w') as f:
        json.dump(items, f, indent=2)

@app.route('/')
def home():
    return jsonify({"status": "Server running"})

@app.route('/dashboard')
def dashboard():
    return open('dashboard.html').read()

@app.route('/manifest.json')
def manifest():
    icon_svg = (
        "data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
        "%3Crect width='100' height='100' rx='18' fill='%230B0E14'/%3E"
        "%3Ctext x='50' y='68' font-size='58' font-family='sans-serif' "
        "font-weight='700' fill='%23E8A33D' text-anchor='middle'%3ET%3C/text%3E"
        "%3C/svg%3E"
    )
    data = {
        "name": "Trading Terminal",
        "short_name": "Terminal",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#0B0E14",
        "theme_color": "#0B0E14",
        "icons": [
            {"src": icon_svg, "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
        ]
    }
    return jsonify(data)

@app.route('/token-status')
def token_status():
    try:
        token = get_token()
    except FileNotFoundError:
        return jsonify({"valid": False, "reason": "token.txt not found"}), 200
    url = "https://api.upstox.com/v2/user/profile"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json().get('data', {})
        return jsonify({"valid": True, "user_name": data.get('user_name'), "email": data.get('email')})
    else:
        return jsonify({"valid": False, "reason": "Token expired or invalid", "details": res.json()})

@app.route('/quote')
def get_quote():
    symbol = request.args.get('symbol', 'NSE_INDEX|Nifty 50')
    url = "https://api.upstox.com/v2/market-quote/quotes"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    params = {"instrument_key": symbol}
    res = requests.get(url, headers=headers, params=params)
    return jsonify(res.json())

@app.route('/optionchain')
def get_option_chain():
    symbol = request.args.get('symbol', 'NSE_INDEX|Nifty 50')
    expiry = request.args.get('expiry', '')
    url = "https://api.upstox.com/v2/option/chain"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    params = {"instrument_key": symbol, "expiry_date": expiry}
    res = requests.get(url, headers=headers, params=params)
    return jsonify(res.json())

@app.route('/option-quote')
def get_option_quote():
    keys = request.args.get('instrument_keys', '')
    if not keys:
        return jsonify({"status": "error", "errors": [{"message": "instrument_keys required"}]})
    url = "https://api.upstox.com/v2/market-quote/quotes"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    params = {"instrument_key": keys}
    res = requests.get(url, headers=headers, params=params)
    return jsonify(res.json())

@app.route('/atr')
def get_atr():
    symbol = request.args.get('symbol', 'NSE_INDEX|Nifty 50')
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=45)).strftime('%Y-%m-%d')
    url = f"https://api.upstox.com/v2/historical-candle/{symbol}/day/{to_date}/{from_date}"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    res = requests.get(url, headers=headers)
    data = res.json()
    if data.get('status') != 'success':
        return jsonify({"status": "error", "errors": data.get('errors', [{"message": "Could not fetch candles"}])})

    candles = data.get('data', {}).get('candles', [])
    candles = list(reversed(candles))[-20:]
    if len(candles) < 2:
        return jsonify({"status": "error", "errors": [{"message": "Not enough candle history"}]})

    trs = []
    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_close = candles[i-1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    period = min(14, len(trs))
    atr = sum(trs[-period:]) / period
    return jsonify({"status": "success", "atr": round(atr, 2), "period": period, "candles_used": len(candles)})

@app.route('/atr15')
def get_atr_15m():
    """ATR(14) computed on 15-minute candles, built by aggregating today's
    1-minute intraday candles. Much tighter than the daily ATR — meant for
    fast/scalping trades rather than full-day swing targets."""
    symbol = request.args.get('symbol', 'NSE_INDEX|Nifty 50')
    url = f"https://api.upstox.com/v2/historical-candle/intraday/{symbol}/1minute"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    res = requests.get(url, headers=headers)
    data = res.json()
    if data.get('status') != 'success':
        return jsonify({"status": "error", "errors": data.get('errors', [{"message": "Could not fetch intraday candles"}])})

    minute_candles = data.get('data', {}).get('candles', [])
    minute_candles = list(reversed(minute_candles))  # oldest to newest
    if len(minute_candles) < 30:
        return jsonify({"status": "error", "errors": [{"message": "Not enough intraday data yet — try again after market has been open a while"}]})

    complete_groups = len(minute_candles) // 15
    minute_candles = minute_candles[-(complete_groups * 15):]

    candles_15m = []
    for i in range(0, len(minute_candles), 15):
        chunk = minute_candles[i:i+15]
        o = chunk[0][1]
        h = max(c[2] for c in chunk)
        l = min(c[3] for c in chunk)
        c_close = chunk[-1][4]
        candles_15m.append([chunk[0][0], o, h, l, c_close])

    if len(candles_15m) < 2:
        return jsonify({"status": "error", "errors": [{"message": "Not enough 15-min candles yet"}]})

    trs = []
    for i in range(1, len(candles_15m)):
        high = candles_15m[i][2]
        low = candles_15m[i][3]
        prev_close = candles_15m[i-1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    period = min(14, len(trs))
    atr = sum(trs[-period:]) / period
    return jsonify({"status": "success", "atr": round(atr, 2), "period": period, "candles_used": len(candles_15m)})

@app.route('/indicators')
def get_indicators():
    """VWAP, RSI(14) on 15-min candles, and a volume participation ratio —
    all computed from today's 1-minute intraday candles."""
    symbol = request.args.get('symbol', 'NSE_INDEX|Nifty 50')
    url = f"https://api.upstox.com/v2/historical-candle/intraday/{symbol}/1minute"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }
    res = requests.get(url, headers=headers)
    data = res.json()
    if data.get('status') != 'success':
        return jsonify({"status": "error", "errors": data.get('errors', [{"message": "Could not fetch intraday candles"}])})

    minute_candles = data.get('data', {}).get('candles', [])
    minute_candles = list(reversed(minute_candles))  # oldest to newest
    if len(minute_candles) < 15:
        return jsonify({"status": "error", "errors": [{"message": "Not enough intraday data yet"}]})

    cum_pv = 0.0
    cum_vol = 0.0
    for c in minute_candles:
        high, low, close, vol = c[2], c[3], c[4], (c[5] or 0)
        typical = (high + low + close) / 3
        cum_pv += typical * vol
        cum_vol += vol
    vwap = (cum_pv / cum_vol) if cum_vol > 0 else None

    latest_vol = minute_candles[-1][5] or 0
    avg_vol = (cum_vol / len(minute_candles)) if minute_candles else 0
    volume_ratio = round(latest_vol / avg_vol, 2) if avg_vol > 0 else None

    complete_groups = len(minute_candles) // 15
    rsi = None
    if complete_groups >= 2:
        trimmed = minute_candles[-(complete_groups * 15):]
        closes_15m = []
        for i in range(0, len(trimmed), 15):
            chunk = trimmed[i:i+15]
            closes_15m.append(chunk[-1][4])
        if len(closes_15m) >= 2:
            gains, losses = [], []
            for i in range(1, len(closes_15m)):
                diff = closes_15m[i] - closes_15m[i-1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            period = min(14, len(gains))
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

    return jsonify({
        "status": "success",
        "vwap": round(vwap, 2) if vwap else None,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "volume_ratio": volume_ratio,
        "last_price": minute_candles[-1][4]
    })

@app.route('/send-signal', methods=['POST'])
def send_signal():
    try:
        bot_token, chat_id = get_telegram_config()
    except FileNotFoundError:
        return jsonify({"ok": False, "reason": "telegram_config.txt not found"}), 200
    except IndexError:
        return jsonify({"ok": False, "reason": "telegram_config.txt needs 2 lines: bot_token, chat_id"}), 200

    body = request.get_json(force=True)
    message = body.get('message', '')

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    res = requests.post(url, json=payload)
    tg_response = res.json()

    if tg_response.get('ok'):
        return jsonify({"ok": True})
    else:
        return jsonify({"ok": False, "reason": tg_response.get('description', 'Telegram API error')})

@app.route('/trades', methods=['GET'])
def get_trades():
    return jsonify(load_trades())

@app.route('/trades', methods=['POST'])
def add_trade():
    trade = request.get_json(force=True)
    trade['id'] = str(uuid.uuid4())[:8]
    trades = load_trades()
    trades.insert(0, trade)
    save_trades(trades)
    return jsonify(trade)

@app.route('/trades/<trade_id>', methods=['PUT'])
def update_trade(trade_id):
    updates = request.get_json(force=True)
    trades = load_trades()
    for t in trades:
        if t['id'] == trade_id:
            t.update(updates)
            save_trades(trades)
            return jsonify(t)
    return jsonify({"error": "Trade not found"}), 404

@app.route('/trades/<trade_id>', methods=['DELETE'])
def delete_trade(trade_id):
    trades = load_trades()
    trades = [t for t in trades if t['id'] != trade_id]
    save_trades(trades)
    return jsonify({"ok": True})

def oi_baseline_path(symbol):
    safe = "".join(c if c.isalnum() else "_" for c in symbol)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), f'oi_baseline_{safe}.json')

@app.route('/oi-baseline', methods=['GET'])
def get_oi_baseline():
    symbol = request.args.get('symbol', '')
    path = oi_baseline_path(symbol)
    if not os.path.exists(path):
        return jsonify(None)
    with open(path) as f:
        return jsonify(json.load(f))

@app.route('/oi-baseline', methods=['POST'])
def save_oi_baseline():
    symbol = request.args.get('symbol', '')
    data = request.get_json(force=True)
    path = oi_baseline_path(symbol)
    with open(path, 'w') as f:
        json.dump(data, f)
    return jsonify({"ok": True})

def build_instrument_caches():
    resp = requests.get(INSTRUMENTS_URL, timeout=60)
    raw = gzip.decompress(resp.content)
    instruments = json.loads(raw)
    eq_list = []
    fo_map = {}
    for inst in instruments:
        if inst.get('instrument_type') == 'EQ' and inst.get('segment') == 'NSE_EQ':
            eq_list.append({
                'symbol': inst.get('trading_symbol'),
                'name': inst.get('name'),
                'instrument_key': inst.get('instrument_key')
            })
        elif inst.get('segment') == 'NSE_FO' and inst.get('lot_size'):
            name = (inst.get('name') or '').upper()
            if name and name not in fo_map:
                fo_map[name] = inst.get('lot_size')
    with open(INSTRUMENTS_CACHE, 'w') as f:
        json.dump(eq_list, f)
    with open(FO_CACHE, 'w') as f:
        json.dump(fo_map, f)
    return eq_list, fo_map

@app.route('/stock-search')
def stock_search():
    q = request.args.get('q', '').strip().upper()
    if len(q) < 2:
        return jsonify([])
    if os.path.exists(INSTRUMENTS_CACHE):
        with open(INSTRUMENTS_CACHE) as f:
            cache = json.load(f)
    else:
        try:
            cache, _ = build_instrument_caches()
        except Exception as e:
            return jsonify({"error": str(e)}), 200
    results = [c for c in cache if q in (c['symbol'] or '').upper() or q in (c['name'] or '').upper()]
    return jsonify(results[:15])

@app.route('/lot-size')
def lot_size():
    name = request.args.get('name', '').strip().upper()
    if not name:
        return jsonify({"lot_size": None})
    if os.path.exists(FO_CACHE):
        with open(FO_CACHE) as f:
            fo_map = json.load(f)
    else:
        try:
            _, fo_map = build_instrument_caches()
        except Exception as e:
            return jsonify({"lot_size": None, "error": str(e)})
    if name in fo_map:
        return jsonify({"lot_size": fo_map[name]})
    for key, val in fo_map.items():
        if name in key or key in name:
            return jsonify({"lot_size": val})
    return jsonify({"lot_size": None})

@app.route('/watchlist', methods=['GET'])
def get_watchlist():
    return jsonify(load_watchlist())

@app.route('/watchlist', methods=['POST'])
def add_watchlist():
    item = request.get_json(force=True)
    items = load_watchlist()
    if not any(i['instrument_key'] == item['instrument_key'] for i in items):
        items.append(item)
        save_watchlist(items)
    return jsonify(items)

@app.route('/watchlist/<path:instrument_key>', methods=['DELETE'])
def delete_watchlist(instrument_key):
    items = load_watchlist()
    items = [i for i in items if i['instrument_key'] != instrument_key]
    save_watchlist(items)
    return jsonify({"ok": True})

@app.route('/crypto-quote')
def crypto_quote():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": "bitcoin", "vs_currencies": "inr", "include_24hr_change": "true"}
    try:
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        btc = data.get('bitcoin', {})
        return jsonify({
            "status": "success",
            "price_inr": btc.get('inr'),
            "change_24h_pct": btc.get('inr_24h_change')
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
