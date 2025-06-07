import websocket, json, time
from collections import deque
from datetime import datetime, timedelta

# === SETTINGS ===
APP_ID = '80484'
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
SYMBOL = 'R_75'

WINDOW_DURATION = 300  # 5 minutes
MOMENTUM_THRESHOLD = 5.0
SNR_TOLERANCE = 30.0

# === DATA ===
price_window = deque()
full_price_history = deque(maxlen=1500)
candles = deque()
support_levels = []
resistance_levels = []
warned_levels = set()
last_signal = None

current_candle = None
last_candle_minute = None

# === TIME SETTINGS ===
RUNNING_TIME_LIMIT = timedelta(hours=12)  # Set the running time limit to 12 hours
start_time = datetime.now()  # Capture the start time when the bot starts

class Candle:
    def __init__(self, timestamp, open_price):
        self.timestamp = timestamp
        self.open = open_price
        self.high = open_price
        self.low = open_price
        self.close = open_price

    def update(self, price):
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price

    def is_bullish(self):
        return self.close > self.open

    def is_bearish(self):
        return self.close < self.open

def detect_support_resistance():
    support_levels.clear()
    resistance_levels.clear()
    prices = [p[1] for p in list(full_price_history)]

    for i in range(5, len(prices) - 5):
        curr = prices[i]
        if all(curr < x for x in prices[i - 5:i]) and all(curr < x for x in prices[i + 1:i + 6]):
            support_levels.append(round(curr, 2))
        elif all(curr > x for x in prices[i - 5:i]) and all(curr > x for x in prices[i + 1:i + 6]):
            resistance_levels.append(round(curr, 2))

def check_proximity(price):
    for level in support_levels + resistance_levels:
        if abs(price - level) <= SNR_TOLERANCE and level not in warned_levels:
            zone = "Support" if level in support_levels else "Resistance"
            print(f"⚠️ WARNING: Price approaching {zone} Zone @ {level}")
            warned_levels.add(level)
            return zone
    return None

def detect_trend(candles):
    if len(candles) < 10:
        return "unknown"

    highs = [candle.high for candle in candles][-10:]
    lows = [candle.low for candle in candles][-10:]

    uptrend = all(earlier < later for earlier, later in zip(highs, highs[1:]))
    downtrend = all(earlier > later for earlier, later in zip(lows, lows[1:]))

    if uptrend:
        return "uptrend"
    elif downtrend:
        return "downtrend"
    return "sideways"

def detect_momentum():
    if len(price_window) < 2:
        return None, 0

    start_price = price_window[0][1]
    end_price = price_window[-1][1]
    change = end_price - start_price

    if abs(change) >= MOMENTUM_THRESHOLD:
        return ("upward" if change > 0 else "downward"), change
    return None, change

def check_signal(price):
    global last_signal
    trend = detect_trend(candles)
    if trend == "sideways":
        return

    if len(candles) < 2:
        return
    last_two = list(candles)[-2:]
    if trend == "uptrend" and not all(c.is_bullish() for c in last_two):
        return
    if trend == "downtrend" and not all(c.is_bearish() for c in last_two):
        return

    direction, strength = detect_momentum()
    if direction is None or direction != trend.replace("trend", ""):
        return

    nearest_zone = min(support_levels + resistance_levels, key=lambda z: abs(price - z), default=None)
    if nearest_zone and abs(price - nearest_zone) <= SNR_TOLERANCE:
        return

    signal = f"✅ VALID {direction.upper()} SIGNAL | Momentum: {strength:.2f}"
    if signal != last_signal:
        print(signal)
        last_signal = signal

# === RUN THE BOT FOR 12 HOURS ===
def run_bot():
    while True:
        # Check how much time has passed since the bot started
        current_time = datetime.now()
        elapsed_time = current_time - start_time

        # If 12 hours have passed, stop the bot
        if elapsed_time >= RUNNING_TIME_LIMIT:
            print("12 hours are up! Stopping the bot.")
            break  # Exit the loop, stopping the bot

        # WebSocket connection
        ws = websocket.WebSocketApp(DERIV_WS_URL,
                                    on_open=on_open,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close)
        ws.run_forever()

        time.sleep(300)  # Wait for 5 minutes before checking again (optional)

# WebSocket callback functions
def on_message(ws, message):
    global current_candle, last_candle_minute

    data = json.loads(message)
    if 'tick' in data:
        tick = data['tick']
        price = round(tick['quote'], 2)
        epoch = tick['epoch']
        minute = datetime.fromtimestamp(epoch).minute

        price_window.append((epoch, price))
        full_price_history.append((epoch, price))
        while price_window and epoch - price_window[0][0] > WINDOW_DURATION:
            price_window.popleft()

        # Candle logic
        if last_candle_minute != minute // 5:
            if current_candle:
                candles.append(current_candle)
            current_candle = Candle(epoch, price)
            last_candle_minute = minute // 5
        else:
            current_candle.update(price)

        if len(full_price_history) >= 100:
            detect_support_resistance()
            zone = check_proximity(price)
            if zone:
                return  # skip signal if near zone
            check_signal(price)

def on_error(ws, error):
    print(f"❌ Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 WebSocket closed.")

def on_open(ws):
    sub_msg = {
        "ticks": SYMBOL,
        "subscribe": 1
    }
    ws.send(json.dumps(sub_msg))
    print(f"📡 Subscribed to {SYMBOL} tick stream...")

# Start the bot
run_bot()
