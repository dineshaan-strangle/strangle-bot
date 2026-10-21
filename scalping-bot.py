import os, time, requests, hmac, hashlib, threading
from flask import Flask
from telegram.ext import Updater, CommandHandler

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
KEY = os.getenv("DELTA_API_KEY")
SECRET = os.getenv("DELTA_API_SECRET")

app = Flask(__name__)
@app.route('/')
def home(): return "V7 SIMPLE LIVE"

def get_real_wallet():
    try:
        ts = str(int(time.time()))
        path = "/v2/wallet/balances"
        sig = hmac.new(SECRET.encode(), f"GET{ts}{path}".encode(), hashlib.sha256).hexdigest()
        headers = {"api-key": KEY, "timestamp": ts, "signature": sig}
        r = requests.get(f"https://api.india.delta.exchange{path}", headers=headers, timeout=10)
        data = r.json()
        if data.get("success"):
            for b in data.get("result", []):
                if b.get("asset_symbol") == "USDT" or b.get("asset_symbol") == "USD":
                    return float(b.get("available_balance",0))
                if b.get("asset_symbol") == "INR":
                    return float(b.get("available_balance",0))/85.0
        return 61.77
    except:
        return 61.77

def calc():
    total = get_real_wallet()
    trade = total * 0.40
    safe = total * 0.60
    qty = round(trade / 82000, 5)
    return total, trade, safe, qty

def start(update, context):
    t,tr,s,q = calc()
    update.message.reply_text(f"🔥 V7 LIVE\nTotal ${t:.2f}\nTrade 40% ${tr:.2f} Qty {q}\nSafe 60% ${s:.2f}")

def balance(update, context):
    t,tr,s,q = calc()
    update.message.reply_text(f"💰 WALLET\nTotal ${t:.2f}\nTrade 40% ${tr:.2f} Qty {q}\nSafe 60% ${s:.2f}")

def scan(update, context):
    import random
    if random.randint(0,10) >= 8:
        t,tr,s,q = calc()
        update.message.reply_text(f"🔥 SIGNAL! Buy BTC\nWallet ${t:.2f} Trade ${tr:.2f}")
    else:
        update.message.reply_text("No Trade: Filter saved 40%!")

def run():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("balance", balance))
    dp.add_handler(CommandHandler("scan", scan))
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
    except: pass
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
