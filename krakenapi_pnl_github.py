import time
import requests
import hashlib
import hmac
import base64
import urllib.parse
import json

#import dontshare_config

#Your API credentials
#API_KEY = dontshare_config.key
#API_SECRET = dontshare_config.secret

# Kraken API URL, API PATHS
base_url = "https://api.kraken.com"
tradeHistory = "/0/private/TradesHistory"
tickerInfo = "/0/public/Ticker"

def get_kraken_signature(urlpath, data, secret):
    """ Generate the Kraken API signature """
    if isinstance(data, str):
        encoded = (str(json.loads(data)["nonce"]) + data).encode()
    else:
        encoded = (str(data["nonce"]) + urllib.parse.urlencode(data)).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

def fetch_all_trades():
    """ Fetches all trades in batches of 50 until no more trades are available. """
    all_trades = {}  
    last_trade_time = None   
    request_count = 0   
    distinct_pairs = set()   

    while True:  
        request_count += 1
        nonce = str(int(time.time() * 1000))

        payload = {
            "nonce": nonce,
            "type": "all",
            "trades": True,
            "consolidate_taker": True
        }

        if last_trade_time:
            payload["end"] = last_trade_time  

        # Generate API signature
        payload_json = json.dumps(payload)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'API-Key': API_KEY,
            'API-Sign': get_kraken_signature(tradeHistory, payload_json, API_SECRET)
        }

        # Send API request
        response = requests.post(base_url + tradeHistory, headers=headers, data=payload_json) 
        response_json = response.json()

        if "error" in response_json and response_json["error"]:
            print(f"Kraken API Error (Trade History): {response_json['error']}")
            break

        trades = response_json.get("result", {}).get("trades", {}) 

        if not trades:
            print("No more trades found. Fetching complete.")
            break

        all_trades.update(trades) 
        distinct_pairs.update(trade["pair"] for trade in trades.values()) 

        last_trade_time = min(float(trade["time"]) for trade in trades.values())

        #Avoid rate limiting
        time.sleep(3)

    return all_trades, distinct_pairs

def get_trade_history_for_pair(pair):
    """ Retrieves trade history for a specific asset pair. """
    all_trades, _ = fetch_all_trades()  

    if not all_trades:
        print("No trade history found.")
        return None

    pair_trades = {trade_id: trade for trade_id, trade in all_trades.items() if trade["pair"] == pair}

    if not pair_trades:
        print(f"No trades found for {pair}.")
        return {}

    return pair_trades

def fetch_market_prices(pairs):             
    
    if isinstance(pairs, str):  
        pairs = [pairs]                    

    if not pairs:
        return {}

    query_pairs = ",".join(pairs)   
    url = f"{base_url}{tickerInfo}?pair={query_pairs}"

    response = requests.get(url)
    response_json = response.json()

    if "error" in response_json and response_json["error"]:
        print(f"Kraken API Error (Market Prices): {response_json['error']}")
        return {} if len(pairs) > 1 else None

    prices = {pair: float(data["c"][0]) for pair, data in response_json.get("result", {}).items()} 
    
    return prices if len(pairs) > 1 else prices.get(pairs[0], None) 


def calculate_unrealized_pnl(pairs=None):
    """Calculates unrealized P&L for one, multiple, or all asset pairs."""

    all_trades, _ = fetch_all_trades()
    if not all_trades:
        print("No trade history found.")
        return None

    trades_by_pair = {}
    for trade_id, trade_data in all_trades.items(): 
        pair = trade_data["pair"]
        volume = float(trade_data["vol"])
        cost = float(trade_data["cost"])
        order_type = trade_data["type"]

        if pair not in trades_by_pair: 
            trades_by_pair[pair] = {"net_volume": 0, "total_cost": 0}

        if order_type == "buy":
            trades_by_pair[pair]["net_volume"] += volume
            trades_by_pair[pair]["total_cost"] += cost
        else:  # sell
            trades_by_pair[pair]["net_volume"] -= volume
            trades_by_pair[pair]["total_cost"] -= cost

    if pairs is None: 
        pairs = list(trades_by_pair.keys()) 
    elif isinstance(pairs, str):
        pairs = [pairs]

    total_unrealized_pnl = 0
    unrealized_pnl_per_pair = {}

    current_prices = fetch_market_prices(pairs)

    for pair in pairs:
        if pair not in trades_by_pair:
            print(f"No trade history found for {pair}.")
            continue 

        if trades_by_pair[pair]["net_volume"] <= 0:
            print(f"No remaining holdings in {pair}.")
            continue

        net_volume = trades_by_pair[pair]["net_volume"]
        total_cost = trades_by_pair[pair]["total_cost"]

        avg_entry_price = total_cost / net_volume
        current_price = float(current_prices) if isinstance(current_prices, (int, float)) else float(current_prices.get(pair, 0))

        if current_price == 0:
            print(f"Failed to fetch market price for {pair}.")
            continue

        unrealized_pnl = (current_price - avg_entry_price) * net_volume
        unrealized_pnl_per_pair[pair] = unrealized_pnl
        total_unrealized_pnl += unrealized_pnl

    print("\nUnrealized P&L for the selected positions:")
    for pair, pnl in unrealized_pnl_per_pair.items():
        print(f"Unrealized P&L for {pair}: {pnl:.2f} USD")

    return round(total_unrealized_pnl, 8)


def calculate_realized_pnl(pairs=None):
    """Calculates realized P&L for one, multiple, or all asset pairs."""

    all_trades, _ = fetch_all_trades()
    if not all_trades:
        print("No trade history found.")
        return None

    # Group trades by pair
    trade_histories = {}
    for trade_id, trade in all_trades.items():
        pair_name = trade["pair"]
        if pair_name not in trade_histories:
            trade_histories[pair_name] = {}
        trade_histories[pair_name][trade_id] = trade

    if pairs is None:
        pairs = list(trade_histories.keys())
    elif isinstance(pairs, str):
        pairs = [pairs]

    total_realized_pnl = 0
    realized_pnl_per_pair = {}

    for pair in pairs:
        if pair not in trade_histories:
            print(f"No trades found for {pair}.")
            continue

        trades = trade_histories[pair]
        realized_pnl = calculate_realized_pnl_from_trades(trades)
        if realized_pnl is not None:
            realized_pnl_per_pair[pair] = realized_pnl
            total_realized_pnl += realized_pnl

    print("\nRealized P&L for the selected positions:")
    for pair, pnl in realized_pnl_per_pair.items():
        print(f"Realized P&L for {pair}: {pnl:.2f} USD")

    return round(total_realized_pnl, 8)


def calculate_realized_pnl_from_trades(pair_trades): #helper for calculate_realized_pnl

    if not pair_trades:
        return None

    realized_pnl = 0
    buy_queue = []

    for trade in sorted(pair_trades.values(), key=lambda x: float(x["time"])):
        volume = float(trade["vol"])
        price = float(trade["price"])
        order_type = trade["type"]

        if order_type == "buy":
            buy_queue.append((price, volume))
        else: #if it's a sell order
            remaining_volume = volume
            while remaining_volume > 0 and buy_queue:
                buy_price, buy_volume = buy_queue.pop(0)  
                matched_volume = min(remaining_volume, buy_volume) 
                realized_pnl += round((price - buy_price) * matched_volume, 8)
                remaining_volume -= matched_volume 

                if buy_volume > matched_volume: 
                    buy_queue.insert(0, (buy_price, buy_volume - matched_volume)) 
                
    return round(realized_pnl, 8)

def calculate_total_pnl():
    """ Combines total unrealized and realized P&L. """
    total_unrealized_pnl = calculate_unrealized_pnl()
    total_realized_pnl = calculate_realized_pnl()

    if total_unrealized_pnl is None:
        total_unrealized_pnl = 0
    if total_realized_pnl is None:
        total_realized_pnl = 0

    total_pnl = total_unrealized_pnl + total_realized_pnl

    print("\n------ Total P&L Summary ------")
    print(f"Total Realized P&L: {total_realized_pnl:.8f} USD")
    print(f"Total Unrealized P&L: {total_unrealized_pnl:.8f} USD")
    print(f"Total Combined P&L: {total_pnl:.8f} USD")

    return total_pnl


'''how to use   

#                             UNREALIZED PNL

calculate_unrealized_pnl("BTCUSD")                              # for one asset pair

calculate_unrealized_pnl(["BTCUSD", "ETHUSD"])                  # multiple asset pairs

total_unrealized_pnl = calculate_unrealized_pnl()               # total unrealized pnl for all asset pairs
if total_unrealized_pnl is not None:
    print(f"\nTotal Unealized P&L: {total_realized_pnl:.8f} USD")

    
    
#                              REALIZED PNL

calculate_realized_pnl("BTCUSD")                                # for one asset pair

calculate_realized_pnl(["BTCUSD", "ETHUSD"])                    # multiple asset pairs

total_realized_pnl = calculate_realized_pnl()                   # total realized pnl for all asset pairs
if total_realized_pnl is not None:
    print(f"\nTotal Realized P&L: {total_realized_pnl:.8f} USD")
                      


#                                TOTAL PNL                       (combining realized and unrealized pnl)

calculate_total_pnl()


'''