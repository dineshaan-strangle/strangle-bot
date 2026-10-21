import os
import time
import threading
from flask import Flask
from telegram.ext import Updater, CommandHandler

# ========== CONFIG ==========
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

TOTAL_WALLET = 61.77
TRADE_PERCENT = 0.40
TRADE_WALLET = round(TOTAL_WALLET * TRADE_PERCENT, 2)  # $24.70
MAIN_WALLET = round(TOTAL_WALLET - TRADE_WALLET, 2)     # $37.07

app = Flask(__name__)

@app.route('/')
def home():
    return f"WORLD BEST V7 ONLINE - Trade ${TRADE_WALLET}"

# ========== TELEGRAM COMMANDS ==========
def start_cmd(update, context):
    msg = f"""🔥 WORLD BEST SCALPING BOT V7 🔥

Total: ${TOTAL_WALLET}
Trade (40%): ${TRADE_WALLET}
Main (60%): ${MAIN_WALLET}

Commands:
/balance - Wallet check
/scan - Market scan
/status - Bot status"""
    update.message.reply_text(msg)

def balance_cmd(update, context):
    msg = f"""💰 WALLET BALANCE 💰

Total Balance: ${TOTAL_WALLET}
Trade Wallet (40%): ${TRADE_WALLET}
Main Wallet (60%): ${MAIN_WALLET}

Trade-ku ready: ${TRADE_WALLET}"""
    update.message.reply_text(msg)

def scan_cmd(update, context):
    update.message.reply_text(f"🔍 Scanning market with ${TRADE_WALLET}...\nNo trade found now. Bot active!")

def status_cmd(update, context):
    update.message.reply_text(f"✅ Bot Live!\nService: https://scalping-bot-q221.onrender.com\nTrade: ${TRADE_WALLET}")

def stop_cmd(update, context):
    update.message.reply_text("🛑 Bot stopped manually. /start to start again.")

# ========== BOT RUNNER - NO CONFLICT, NO SIGNAL ERROR ==========
def run_bot():
    print("WORLD BEST V7 ONLINE!")
    try:
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        dp.add_handler(CommandHandler("start", start_cmd))
        dp.add_handler(CommandHandler("balance", balance_cmd))
        dp.add_handler(CommandHandler("scan", scan_cmd))
        dp.add_handler(CommandHandler("status", status_cmd))
        dp.add_handler(CommandHandler("stop", stop_cmd))

        # Kill duplicate webhooks - Conflict fix
        updater.bot.delete_webhook(drop_pending_updates=True)
        print("Webhook deleted - Conflict cleared")

        # Start polling without idle() - Signal error fix
        updater.start_polling(drop_pending_updates=True, clean=True, timeout=30)
        print(f"Polling started - Trade Wallet ${TRADE_WALLET} - No Conflict!")

        # Keep thread alive forever
        while True:
            time.sleep(60)
            
    except Exception as e:
        print(f"Bot Error: {e}")
        print("10 sec wait & retry...")
        time.sleep(10)
        run_bot()

# ========== MAIN - RENDER KU ==========
if __name__ == "__main__":
    # Bot-a thread la odu, Flask-a main la odu
    threading.Thread(target=run_bot, daemon=True).start()
    print(f"Flask starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
