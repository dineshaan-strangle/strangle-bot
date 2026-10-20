import os
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")
DELTA_API_KEY = os.environ.get("DELTA_API_KEY")
DELTA_API_SECRET = os.environ.get("DELTA_API_SECRET")
from flask import Flask
import threading
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot Running!"
def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
threading.Thread(target=run_web, daemon=True).start()
import time, hmac, hashlib, requests, json, datetime, os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest
DELTA_BASE_URL = "https://api.india.delta.exchange"
selection = {"pe": None, "ce": None, "mode": None}
SL_MULTIPLIER = 2.0
SMART_ENABLED = False
COLLECTED_COMBINED = 0.0
SMART_SL_COMBINED = 0.0
LAST_SCAN_HEADER = ""
LAST_ATM_INFO = {}
PREV_PE_STRIKE = None
PREV_CE_STRIKE = None
PREV_TOTAL_USD = 0.0
CONFIG_FILE = "timer_config.json"
QTY = 25
AUTO_QTY_MODE = True
FUNDS_PER_50_LOTS = 56.93
TIMER_CONFIG = {
    "auto_on": "21:30",
    "auto_off": "05:20",
    "manual_override": None,
    "trading_active": False,
    "custom_range": None
}
def load_config():
    global QTY, TIMER_CONFIG, AUTO_QTY_MODE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE,'r') as f:
                data=json.load(f); TIMER_CONFIG.update(data); QTY=TIMER_CONFIG.get("qty",25); AUTO_QTY_MODE=TIMER_CONFIG.get("auto_qty",True)
        except: pass
def save_config():
    TIMER_CONFIG["qty"]=QTY
    TIMER_CONFIG["auto_qty"]=AUTO_QTY_MODE
    with open(CONFIG_FILE,'w') as f: json.dump(TIMER_CONFIG,f)
def parse_time_str(tstr):
    try: h,m=map(int,tstr.split(':')); return datetime.time(h,m)
    except: return None
def is_trading_allowed():
    if TIMER_CONFIG["manual_override"] is True: return True
    if TIMER_CONFIG["manual_override"] is False: return False
    if TIMER_CONFIG["custom_range"]:
        try:
            s,e=TIMER_CONFIG["custom_range"]; st=parse_time_str(s); et=parse_time_str(e); now=datetime.datetime.now().time()
            if st<=et: return st<=now<=et
            else: return now>=st or now<=et
        except: pass
    if TIMER_CONFIG["auto_on"] and TIMER_CONFIG["auto_off"]:
        st=parse_time_str(TIMER_CONFIG["auto_on"]); et=parse_time_str(TIMER_CONFIG["auto_off"])
        if not st or not et: return TIMER_CONFIG.get("trading_active",True)
        now=datetime.datetime.now().time()
        if st<=et: return st<=now<=et
        else: return now>=st or now<=et
    return TIMER_CONFIG.get("trading_active",True)
def get_wallet_balance():
    try:
        j = delta_request("GET","/wallet/balances",auth_required=True)
        for b in j.get('result',[]):
            if b.get('asset_symbol') in ['USD','USDT','USDC']:
                return float(b.get('available_balance', 64.96))
        return 64.96
    except:
        return 64.96
def get_lot_size_for_trade():
    global QTY, AUTO_QTY_MODE
    if AUTO_QTY_MODE:
        try:
            available = get_wallet_balance()
            funds_per_lot = FUNDS_PER_50_LOTS / 50.0
            max_total_lots = int(available / funds_per_lot)
            qty_per_side = max_total_lots // 2
            if qty_per_side < 1: qty_per_side = 1
            if qty_per_side > 50: qty_per_side = 50
            return -0.001 * float(qty_per_side)
        except:
            return -0.001 * float(QTY)
    else:
        return -0.001 * float(QTY)
def get_current_qty_per_side():
    lot = abs(get_lot_size_for_trade())
    return int(lot*1000)
load_config()
def get_trailing_sl(collected_premium, current_combined_premium):
    activation=collected_premium*0.60; initial_sl=collected_premium*0.50; slab=collected_premium*0.10
    if current_combined_premium<activation: return None
    slabs_crossed=int((current_combined_premium-activation)//slab)
    trailing_sl=initial_sl+(slabs_crossed*slab); max_sl=collected_premium-slab
    return min(trailing_sl,max_sl)
def get_signature(msg, secret): return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
def delta_request(method, endpoint, payload="", auth_required=True):
    path=f"/v2{endpoint}"; url=DELTA_BASE_URL+path; headers={'Content-Type':'application/json'}
    if auth_required:
        ts=str(int(time.time())); sig=get_signature(method+ts+path+payload, DELTA_API_SECRET)
        headers.update({'api-key':DELTA_API_KEY,'timestamp':ts,'signature':sig})
    r=requests.request(method, url, data=payload, headers=headers, timeout=15); j=r.json()
    if j.get('error'):
        code=j['error'].get('code','')
        if code=='ip_not_whitelisted_for_api_key':
            ip=j['error'].get('context',{}).get('client_ip','YOUR_IP'); raise Exception(f"IP_NOT_WHITELISTED: Add {ip}")
        if "positions" in endpoint and code=='not_found': return {"result":[]}
        if "orders" in endpoint and "not_found" in str(j['error']): return {"result":[]}
        raise Exception(f"{j['error']}")
    return j
def get_btc_spot_live(): return float(delta_request("GET","/tickers/BTCUSD",auth_required=False)['result']['mark_price'])
def get_t2_chain_live():
    prods=delta_request("GET","/products",auth_required=False)['result']; now_ts=time.time(); calls={}; puts={}
    for p in prods:
        sym=p.get('symbol','')
        if not (sym.startswith("C-BTC-") or sym.startswith("P-BTC-")): continue
        st=p.get('settlement_time');
        if not st: continue
        exp=datetime.datetime.fromisoformat(st.replace('Z','+00:00')).timestamp(); days=(exp-now_ts)/86400
        if not (1.5<=days<=2.5): continue
        try: strike=int(float(sym.split('-')[2]))
        except: continue
        if sym.startswith("C-BTC-"): calls[strike]=p
        else: puts[strike]=p
    return calls, puts
def get_atm_info_live():
    spot=get_btc_spot_live(); calls,puts=get_t2_chain_live()
    common=sorted(set(calls.keys()) & set(puts.keys())); atm=min(common, key=lambda x: abs(x-spot))
    c_prod=calls[atm]; p_prod=puts[atm]
    c_tick=delta_request("GET",f"/tickers/{c_prod['symbol']}",auth_required=False)['result']
    p_tick=delta_request("GET",f"/tickers/{p_prod['symbol']}",auth_required=False)['result']
    c_prem=float(c_tick.get('mark_price')); p_prem=float(p_tick.get('mark_price'))
    if c_prem<10: c_prem*=spot
    if p_prem<10: p_prem*=spot
    return int(spot), atm, int(c_prem), int(p_prem), calls, puts
def get_ltp_live_strict(strike, otype, calls, puts, spot):
    try:
        avail_dict = calls if otype=="C" else puts
        if not avail_dict:
            return spot, 0, "", {}
        if strike not in avail_dict:
            nearest = min(avail_dict.keys(), key=lambda x: abs(x - strike))
            strike = nearest
        prod = avail_dict[strike]
        tick = delta_request("GET", f"/tickers/{prod['symbol']}", auth_required=False)['result']
        ltp = float(tick.get('mark_price') or 0)
        if ltp < 10:
            ltp = spot
        return ltp, prod.get('id', 0), prod.get('symbol', ''), prod
    except Exception as e:
        return spot, 0, "", {}
BOT_PRODUCTS_FILE = "bot_products.json"
def load_bot_products():
    try:
        if os.path.exists(BOT_PRODUCTS_FILE):
            with open(BOT_PRODUCTS_FILE,'r') as fd:
                data=json.load(fd)
                if not data: return []
                clean=[]
                for x in data:
                    if isinstance(x, int): clean.append(x)
                    elif isinstance(x, dict) and 'id' in x: clean.append(int(x['id']))
                return clean
    except: pass
    return []
def save_bot_products(pids):
    try:
        with open(BOT_PRODUCTS_FILE,'w') as fd:
            json.dump([int(x) for x in pids], fd)
    except: pass
def add_bot_product(pid):
    try:
        pids=load_bot_products()
        if int(pid) not in pids:
            pids.append(int(pid))
            save_bot_products(pids)
    except: pass
def remove_bot_products(pids_to_remove):
    try:
        cur=load_bot_products()
        rem=[p for p in cur if p not in [int(x) for x in pids_to_remove]]
        save_bot_products(rem)
    except: save_bot_products([])
def get_positions_live():
    j=delta_request("GET","/positions?underlying_asset_symbol=BTC",auth_required=True)
    pe=None; ce=None; all_pos=[]
    for pos in j.get('result',[]):
        size=float(pos.get('size',0) or 0)
        if size>=0: continue
        all_pos.append(pos)
        prod=pos.get('product',{})
        sym=prod.get('symbol','')
        try: strike=int(float(sym.split('-')[2]))
        except: strike=int(float(prod.get('strike_price',0) or 0))
        entry=float(pos.get('entry_price',0))
        if prod.get('contract_type')=='put_options': pe=(strike,entry,size,prod)
        if prod.get('contract_type')=='call_options': ce=(strike,entry,size,prod)
    return pe, ce, all_pos
def close_bot_positions_only():
    bot_pids = load_bot_products()
    bot_set = set([int(x) for x in bot_pids]) if bot_pids else set()
    if not bot_set: return [], []
    try: j = delta_request("GET", "/positions?underlying_asset_symbol=BTC", auth_required=True)
    except: return [], []
    all_pos = j.get('result', []) if isinstance(j, dict) else []
    closed = []; closed_pids = []
    for pos in all_pos:
        try:
            size = float(pos.get('size', 0) or 0)
            prod = pos.get('product', {}) or {}
            pid = prod.get('id') or pos.get('product_id')
            sym = prod.get('symbol','') or prod.get('contract_symbol','')
            if size >= 0: continue
            if not pid: continue
            pid_int = int(pid)
            if pid_int not in bot_set: continue
            contracts = int(abs(size)*1000) if abs(size)<1 else int(abs(size))
            if contracts==0: contracts=1
            payload = json.dumps({"product_id": int(pid_int), "size": contracts, "side": "buy", "order_type": "market_order", "time_in_force": "ioc"})
            delta_request("POST", "/orders", payload, auth_required=True)
            if not sym: sym = f"PID-{pid_int}"
            closed.append(sym); closed_pids.append(pid_int)
            time.sleep(1.0)
        except: continue
    if closed_pids: remove_bot_products(closed_pids)
    return closed, closed_pids
def cancel_bot_sl_only(bot_pids):
    bot_set = set([int(x) for x in bot_pids]) if bot_pids else set()
    if not bot_set: return []
    cancelled = []
    for pid in bot_set:
        try:
            payload = json.dumps({"product_id": int(pid), "cancel_stop_orders": True, "cancel_limit_orders": True})
            delta_request("DELETE", "/orders/all", payload, auth_required=True)
            cancelled.append(str(pid)); time.sleep(0.5)
        except:
            try:
                payload2 = json.dumps({"product_id": int(pid)})
                delta_request("DELETE", "/orders/all", payload2, auth_required=True)
                cancelled.append(str(pid))
            except: pass
    return cancelled
def force_cancel_all_orders():
    cancelled=[]; closed=[]
    try:
        j = delta_request("GET", "/positions?underlying_asset_symbol=BTC", auth_required=True)
        all_pos = j.get('result', []) if isinstance(j, dict) else []
        for pos in all_pos:
            try:
                size = float(pos.get('size', 0) or 0)
                if size >= 0: continue
                prod = pos.get('product', {}) or {}
                pid = prod.get('id') or pos.get('product_id')
                sym = prod.get('symbol','') or prod.get('contract_symbol','')
                if not pid: continue
                contracts = int(abs(size)*1000) if abs(size)<1 else int(abs(size))
                if contracts==0: contracts=1
                payload = json.dumps({"product_id": int(pid), "size": contracts, "side": "buy", "order_type": "market_order", "time_in_force": "ioc"})
                delta_request("POST", "/orders", payload, auth_required=True)
                closed.append(str(sym or pid)); time.sleep(0.6)
            except: continue
    except: pass
    try:
        payload = json.dumps({"contract_types": "call_options,put_options", "cancel_stop_orders": True, "cancel_limit_orders": True})
        delta_request("DELETE", "/orders/all", payload, auth_required=True)
        cancelled.append("ALL_OPTIONS")
    except: pass
    try:
        payload2 = json.dumps({"cancel_stop_orders": True, "cancel_limit_orders": True})
        delta_request("DELETE", "/orders/all", payload2, auth_required=True)
        cancelled.append("ALL")
    except: pass
    return cancelled, closed

def execute_auto_timer_trade():
    try:
        pe_exist, ce_exist, _ = get_positions_live()
        if pe_exist and ce_exist:
            return False
        spot, atm, cp, pp, calls, puts = get_atm_info_live()
        combined = cp + pp
        ideal = int(combined * 2)
        avail = sorted(calls.keys())
        suggested_pe = min(avail, key=lambda x: abs(x - (atm - ideal)))
        suggested_ce = min(avail, key=lambda x: abs(x - (atm + ideal)))
        lot_size = get_lot_size_for_trade()
        pe_ltp, pe_pid, _, _ = get_ltp_live_strict(suggested_pe, "P", calls, puts, spot)
        ce_ltp, ce_pid, _, _ = get_ltp_live_strict(suggested_ce, "C", calls, puts, spot)
        cb, pids = close_bot_positions_only()
        time.sleep(0.5)
        close_sl_only_for_bot_products(pids)
        time.sleep(0.5)
        place_order_live_with_retry(pe_pid, lot_size, "sell")
        time.sleep(0.6)
        add_bot_product(pe_pid)
        place_order_live_with_retry(ce_pid, lot_size, "sell")
        time.sleep(0.5)
        add_bot_product(ce_pid)
        place_sl_live(pe_pid, lot_size, pe_ltp)
        place_sl_live(ce_pid, lot_size, ce_ltp)
        global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
        COLLECTED_COMBINED = pe_ltp + ce_ltp
        SMART_ENABLED = True
        SMART_SL_COMBINED = 0
        return True
    except Exception as e:
        print(f"Auto Timer Trade Error: {e}")
        return False

def close_sl_only_for_bot_products(product_ids):
    if not product_ids: product_ids = load_bot_products()
    return cancel_bot_sl_only(product_ids)

def get_live_pnl_from_delta_strict_margin():
    total_usd = 0.0
    details = []
    try:
        j = delta_request("GET", "/positions?underlying_asset_symbol=BTC", auth_required=True)
        res = j.get('result', [])
        if not res:
            return 0.0, 0.0, ["No open option positions"]
        for pos in res:
            try:
                size_contracts = float(pos.get('size', 0) or 0)
                if size_contracts == 0:
                    continue
                size_btc = abs(size_contracts) * 0.001
                entry = float(pos.get('entry_price', 0) or 0)
                prod_id = pos.get('product_id')
                if not prod_id:
                    continue
                try:
                    p_info = delta_request("GET", f"/products/{prod_id}", auth_required=False)
                    sym = p_info.get('result', {}).get('symbol', f'PID-{prod_id}')
                    t_info = delta_request("GET", f"/tickers/{sym}", auth_required=False)
                    mark = float(t_info['result'].get('mark_price', entry) or entry)
                    if mark < 10:
                        spot = get_btc_spot_live()
                        mark = mark * spot
                except:
                    mark = entry
                    sym = f'PID-{prod_id}'
                pnl = (entry - mark) * size_btc
                total_usd += pnl
                details.append(f"{sym}\n  Entry ${entry:.2f} -> Now ${mark:.2f}\n  {abs(size_contracts)} lots ({size_btc:.4f} BTC) => PNL ${pnl:.4f} USD")
            except Exception as e:
                details.append(f"Error: {e}")
                continue
    except Exception as e:
        return 0.0, 0.0, [f"Error: {e}"]
    if not details:
        return 0.0, 0.0, ["No positions"]
    return total_usd, total_usd*85.0, details

def place_order_live_with_retry(pid,size,side, retries=2):
    fsize=abs(float(size)); contracts=int(fsize*1000) if fsize<1 else int(fsize)
    if contracts==0: contracts=1
    payload=json.dumps({"product_id":pid,"size":contracts,"side":side,"order_type":"market_order","time_in_force":"ioc"})
    last_err=None
    for i in range(retries+1):
        try: return delta_request("POST","/orders",payload,auth_required=True)
        except Exception as e: last_err=e; time.sleep(0.8)
    raise last_err

def place_sl_live(pid,size,entry_price):
    try: cancel_bot_sl_only([pid])
    except: pass
    fsize=abs(float(size)); contracts=int(fsize*1000) if fsize<1 else int(fsize)
    if contracts==0: contracts=1
    sl_price=float(entry_price)*SL_MULTIPLIER
    payload=json.dumps({"product_id":pid,"size":contracts,"side":"buy","order_type":"limit_order","limit_price":str(round(sl_price,2)),"stop_order_type":"stop_loss_order","stop_price":str(round(sl_price,2)),"time_in_force":"gtc"})
    try: return delta_request("POST","/orders",payload,auth_required=True)
    except: return None

def get_combined_ltp_live():
    pe,ce,_=get_positions_live()
    if not pe or not ce: return None
    calls,puts=get_t2_chain_live(); spot=get_btc_spot_live()
    try:
        pe_ltp,_,_,_=get_ltp_live_strict(pe[0],"P",calls,puts,spot)
        ce_ltp,_,_,_=get_ltp_live_strict(ce[0],"C",calls,puts,spot)
        return pe_ltp+ce_ltp
    except: return None

async def smart_trail_job(context):
    global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
    if not SMART_ENABLED or COLLECTED_COMBINED==0: return
    try:
        combined=get_combined_ltp_live()
        if combined is None: return
        new_sl=get_trailing_sl(COLLECTED_COMBINED, combined)
        if new_sl is not None:
            if SMART_SL_COMBINED==0:
                SMART_SL_COMBINED=new_sl
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 2 - TRAIL ACTIVATED\nCollected: ${COLLECTED_COMBINED:.2f}\nSL SET: ${SMART_SL_COMBINED:.2f}")
            elif new_sl>SMART_SL_COMBINED:
                old_sl=SMART_SL_COMBINED; SMART_SL_COMBINED=new_sl
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 2 - TRAILING SL MOVED\nFrom: ${old_sl:.2f} -> To: ${SMART_SL_COMBINED:.2f}\nCombined: ${combined:.2f}")
            if combined<=SMART_SL_COMBINED:
                total_usd,_,_=get_live_pnl_from_delta_strict_margin()
                closed, pids = close_bot_positions_only(); close_sl_only_for_bot_products(pids)
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 2/3 - TRAIL SL HIT EXIT\nCombined ${combined:.2f} <= SL ${SMART_SL_COMBINED:.2f}\nClosed: {', '.join(closed)}\nFINAL {total_usd:.4f} USD")
                SMART_ENABLED=False; COLLECTED_COMBINED=0; SMART_SL_COMBINED=0
    except: pass

async def individual_sl_monitor_job(context):
    global PREV_PE_STRIKE, PREV_CE_STRIKE, PREV_TOTAL_USD, SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
    try:
        pe,ce,_=get_positions_live(); total_usd,_,_=get_live_pnl_from_delta_strict_margin()
        curr_pe=pe[0] if pe else None; curr_ce=ce[0] if ce else None
        if PREV_PE_STRIKE is not None and curr_pe is None and PREV_CE_STRIKE is not None:
            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 1 - PE STOP LOSS HIT\nPE {PREV_PE_STRIKE} EXITED\nPNL {PREV_TOTAL_USD:.4f} USD")
            close_sl_only_for_bot_products([])
        if PREV_CE_STRIKE is not None and curr_ce is None and PREV_PE_STRIKE is not None:
            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 1 - CE STOP LOSS HIT\nCE {PREV_CE_STRIKE} EXITED\nPNL {PREV_TOTAL_USD:.4f} USD")
            close_sl_only_for_bot_products([])
        if PREV_PE_STRIKE is not None and PREV_CE_STRIKE is not None and curr_pe is None and curr_ce is None:
            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ALERT 3 - FINAL EXIT\nBoth closed PE {PREV_PE_STRIKE} + CE {PREV_CE_STRIKE}\nFinal {PREV_TOTAL_USD:.4f} USD")
            close_sl_only_for_bot_products([])
            SMART_ENABLED=False; COLLECTED_COMBINED=0; SMART_SL_COMBINED=0
        PREV_PE_STRIKE=curr_pe; PREV_CE_STRIKE=curr_ce
        if total_usd!=0: PREV_TOTAL_USD=total_usd
    except: pass

async def timer_auto_job(context):
    global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
    try:
        if TIMER_CONFIG["manual_override"] is not None:
            return
        now_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
        now_str = now_dt.strftime("%H:%M")
        print(f"[{now_str} IST] TIMER CHECK Custom:{TIMER_CONFIG['custom_range']} Auto ON:{TIMER_CONFIG['auto_on']}")
        if TIMER_CONFIG["auto_on"] and not TIMER_CONFIG["custom_range"]:
            if now_str == TIMER_CONFIG.get("auto_on"):
                if not TIMER_CONFIG.get("trading_active"):
                    TIMER_CONFIG["trading_active"] = True
                    save_config()
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"AUTO TIMER ON {now_str} - Trading ENABLED + Taking Trade...")
                    try:
                        if execute_auto_timer_trade():
                            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ AUTO TIMER TRADE DONE - {now_str}")
                    except Exception as e:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Auto trade error: {e}")
        if TIMER_CONFIG["auto_off"] and not TIMER_CONFIG["custom_range"]:
            if now_str == TIMER_CONFIG.get("auto_off"):
                if TIMER_CONFIG.get("trading_active") or is_trading_allowed():
                    TIMER_CONFIG["trading_active"] = False
                    save_config()
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"AUTO TIMER OFF {now_str} - Closing all bot positions...")
                    try:
                        closed, pids = close_bot_positions_only()
                        close_sl_only_for_bot_products(pids)
                        SMART_ENABLED = False; COLLECTED_COMBINED = 0; SMART_SL_COMBINED = 0
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ AUTO CLOSE DONE\nClosed: {', '.join(closed) if closed else 'No bot positions'}")
                    except Exception as e:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Auto close error: {e}")
        if TIMER_CONFIG["custom_range"]:
            try:
                s, e = TIMER_CONFIG["custom_range"]
                if now_str == s:
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"CUSTOM TIMER ON {now_str} - Taking Trade...")
                    try:
                        if execute_auto_timer_trade():
                            await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ CUSTOM TIMER TRADE DONE\n\nBTC: ${btc_price}\nCE Strike: {ce_strike} ({ce_qty} Lots)\nPE Strike: {pe_strike} ({pe_qty} Lots)\nATM Strangle Taken at {now_str} IST")
                    except Exception as ex:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Custom trade error: {ex}")
                if now_str == e:
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"CUSTOM TIMER OFF {now_str} - Closing all bot positions...")
                    try:
                        closed, pids = close_bot_positions_only()
                        close_sl_only_for_bot_products(pids)
                        SMART_ENABLED = False; COLLECTED_COMBINED = 0; SMART_SL_COMBINED = 0
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ CUSTOM CLOSE DONE\nClosed: {', '.join(closed) if closed else 'No bot positions'}")
                        TIMER_CONFIG["custom_range"] = None
                        save_config()
                    except Exception as ex:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Custom close error: {ex}")
            except: pass
    except Exception as ex:
        pass
async def qty_command(update, context):
    global QTY, AUTO_QTY_MODE
    if not context.args:
        mode_txt = "AUTO (Same Qty Both Side)" if AUTO_QTY_MODE else f"MANUAL {QTY}+{QTY}"
        curr_qty = get_current_qty_per_side()
        await update.message.reply_text(f"Current Mode: {mode_txt}\nLive QTY: {curr_qty}+{curr_qty} = {curr_qty*2} Total\nBase: 50 Lots = {FUNDS_PER_50_LOTS}$\n\nUsage:\n/qty auto -> Auto Wallet Base\n/qty 25 -> Manual 25+25\n/qty 43 -> Manual 43+43"); return
    arg = context.args[0].lower()
    if arg == "auto":
        AUTO_QTY_MODE=True; save_config()
        curr_qty = get_current_qty_per_side()
        bal = get_wallet_balance()
        await update.message.reply_text(f"✅ AUTO MODE ON\nWallet: ${bal:.2f}\nBase: 50 Lots = ${FUNDS_PER_50_LOTS}\nAuto QTY: {curr_qty} Call + {curr_qty} Put = {curr_qty*2} Lots Total\nSame Qty Confirmed ✅")
        return
    try:
        q=int(context.args[0])
        if q<1 or q>100: await update.message.reply_text("QTY 1 to 100 only"); return
        QTY=q; AUTO_QTY_MODE=False; save_config()
        await update.message.reply_text(f"✅ MANUAL MODE\nQTY set to {QTY} Call + {QTY} Put = {QTY*2} Total\nSame Qty Both Side ✅\nSize: {abs(get_lot_size_for_trade()):.4f} BTC")
    except: await update.message.reply_text("Invalid. Use /qty auto or /qty 25")

async def setontime_command(update, context):
    if not context.args: await update.message.reply_text(f"ON: {TIMER_CONFIG['auto_on']}\nUsage: /setontime 21:30"); return
    t=context.args[0]
    if not parse_time_str(t): await update.message.reply_text("Invalid time"); return
    TIMER_CONFIG["auto_on"]=t; TIMER_CONFIG["manual_override"]=None; save_config()
    await update.message.reply_text(f"✅ Auto ON set to {t}")

async def setofftime_command(update, context):
    if not context.args: await update.message.reply_text(f"OFF: {TIMER_CONFIG['auto_off']}\nUsage: /setofftime 15:15"); return
    t=context.args[0]
    if not parse_time_str(t): await update.message.reply_text("Invalid time"); return
    TIMER_CONFIG["auto_off"]=t; TIMER_CONFIG["manual_override"]=None; save_config()
    await update.message.reply_text(f"✅ Auto OFF set to {t}")

async def timer_command(update, context):
    if not context.args:
        await update.message.reply_text("Usage:\n/timer on\n/timer off\n/timer 21:30-23:00\n/timer auto"); return
    arg=context.args[0].lower()
    if arg=="on":
        TIMER_CONFIG["manual_override"]=True; TIMER_CONFIG["trading_active"]=True; save_config()
        await update.message.reply_text("✅ TIMER Manual ON")
    elif arg=="off":
        TIMER_CONFIG["manual_override"]=False; TIMER_CONFIG["trading_active"]=False; save_config()
        await update.message.reply_text("❌ TIMER Manual OFF")
    elif arg=="auto":
        TIMER_CONFIG["manual_override"]=None; TIMER_CONFIG["custom_range"]=None; save_config()
        await update.message.reply_text(f"✅ AUTO ON:{TIMER_CONFIG['auto_on']} OFF:{TIMER_CONFIG['auto_off']}")
    elif "-" in arg:
        try:
            s,e = arg.split('-')
            if not parse_time_str(s) or not parse_time_str(e): raise ValueError
            TIMER_CONFIG["custom_range"]=[s,e]; TIMER_CONFIG["manual_override"]=None; save_config()
            await update.message.reply_text(f"✅ Custom Timer {s} to {e} - Auto Trade + Auto Close ✅")
        except: await update.message.reply_text("Invalid range. Ex: /timer 21:30-23:00")
    else: await update.message.reply_text("Invalid. Use /timer on / off / auto")

async def timersettings_command(update, context):
    status="ENABLED" if is_trading_allowed() else "DISABLED"
    curr_qty = get_current_qty_per_side()
    mode_txt = "AUTO" if AUTO_QTY_MODE else "MANUAL"
    txt=f"TIMER SETTINGS\nMode: {mode_txt}\nQTY: {curr_qty}+{curr_qty} = {curr_qty*2} Lots = {abs(get_lot_size_for_trade()):.4f} BTC\nWallet: ${get_wallet_balance():.2f}\nAuto ON: {TIMER_CONFIG['auto_on']}\nAuto OFF: {TIMER_CONFIG['auto_off']}\nStatus: {status}\n\nUse: /qty auto | /qty 25"
    kb=[[InlineKeyboardButton("Timer ON", callback_data="TIMER_ON"), InlineKeyboardButton("Timer OFF", callback_data="TIMER_OFF"), InlineKeyboardButton("AUTO", callback_data="TIMER_AUTO")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def start_command(update, context):
    spot=get_btc_spot_live(); status="ENABLED" if is_trading_allowed() else "DISABLED"
    curr_qty = get_current_qty_per_side()
    mode_txt = "AUTO Same Qty" if AUTO_QTY_MODE else f"MANUAL {QTY}+{QTY}"
    txt=f"V101 AUTO TRADE TIMER ✅\nBTC ${spot}\nMode: {mode_txt}\nQTY: {curr_qty}+{curr_qty} = {curr_qty*2} Lots | Timer: {status}\n/close = Bot Only SAFE | /cleanall = FULL WIPE"
    kb=[[InlineKeyboardButton("Scan Trade", callback_data="DO_SCAN")],[InlineKeyboardButton("LIVE PNL", callback_data="LIVE_PNL")],[InlineKeyboardButton("Timer Settings", callback_data="TIMER_SETTINGS")],[InlineKeyboardButton("CLOSE BOT ONLY", callback_data="CLOSE_ALL")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def livepnl_command(update, context):
    total_usd, total_inr, details=get_live_pnl_from_delta_strict_margin(); spot=get_btc_spot_live()
    header = f"💰 V101 LIVE PNL\nBTC ${spot}\nMode: {'AUTO' if AUTO_QTY_MODE else 'MANUAL'} QTY: {get_current_qty_per_side()}+{get_current_qty_per_side()}\nTotal UPNL: ${total_usd:.2f} USD = {total_inr:.2f} INR\n"
    txt = header + "\n" + "\n\n".join(details) if details else f"LIVE PNL\nBTC ${spot}\nNo positions\nTotal UPNL: $0.00"
    await update.message.reply_text(txt)

async def close_command(update, context):
    global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
    await update.message.reply_text("⏳ V101 CLOSE... BOT ONLY...")
    full_bot_pids = load_bot_products()
    closed, pids = close_bot_positions_only()
    closed_sl = cancel_bot_sl_only(full_bot_pids if full_bot_pids else pids)
    SMART_ENABLED=False; COLLECTED_COMBINED=0; SMART_SL_COMBINED=0
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ V101 CLOSED - Manual SAFE\nBot Trade: {', '.join(closed) if closed else 'No bot pos'}\nBot SL: {len(closed_sl)} cancelled\nFile: {load_bot_products()}")

async def cleanall_command(update, context):
    await update.message.reply_text("⚠️ V101 FORCE CLEAN ALL...")
    cancelled, closed = force_cancel_all_orders()
    save_bot_products([])
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"✅ V101 FORCE CLEAN DONE\nClosed: {', '.join(closed) if closed else 'None'}\nOrders: {cancelled}\nFile cleared []")

async def scantrade_command(update, context):
    global LAST_SCAN_HEADER, LAST_ATM_INFO, selection
    if not is_trading_allowed():
        await update.message.reply_text(f"⏰ TIMER BLOCKED\nQTY: {get_current_qty_per_side()}+{get_current_qty_per_side()}\nUse /timer on"); return
    spot,atm,cp,pp,calls,puts=get_atm_info_live(); pe,ce,_=get_positions_live()
    combined=cp+pp; ideal=int(combined*2); pe_target=atm-ideal; ce_target=atm+ideal
    avail=sorted(calls.keys())
    suggested_pe=min(avail, key=lambda x: abs(x-pe_target)); suggested_ce=min(avail, key=lambda x: abs(x-ce_target))
    pe_ltp_sugg,_,_,_=get_ltp_live_strict(suggested_pe,"P",calls,puts,spot)
    ce_ltp_sugg,_,_,_=get_ltp_live_strict(suggested_ce,"C",calls,puts,spot)
    sel_txt=f"PE {pe[0]} | CE {ce[0]}" if pe and ce else "No position"
    curr_qty = get_current_qty_per_side()
    mode_txt = "AUTO" if AUTO_QTY_MODE else "MANUAL"
    LAST_SCAN_HEADER=f"V101 SCAN | {mode_txt} QTY:{curr_qty}+{curr_qty}={curr_qty*2}\nBTC ${spot} ATM {atm} CALL ${cp} PUT ${pp}\nCURRENT: {sel_txt}\nSUGGESTED (x2={ideal}):\nPE {suggested_pe} @ ${pe_ltp_sugg:.0f}\nCE {suggested_ce} @ ${ce_ltp_sugg:.0f}"
    LAST_ATM_INFO={"spot":spot,"atm":atm,"cp":cp,"pp":pp,"combined":combined,"sug_pe":suggested_pe,"sug_ce":suggested_ce,"ideal":ideal}
    selection["pe"]=suggested_pe; selection["ce"]=suggested_ce; selection["mode"]="MOVE_BOTH"
    text=f"{LAST_SCAN_HEADER}\n\nMode: {mode_txt} QTY: {curr_qty}+{curr_qty}\nMaathanumna /qty auto | /qty 25"
    kb=[[InlineKeyboardButton(f"TRADE PE {suggested_pe} + CE {suggested_ce} (Both) QTY:{curr_qty}+{curr_qty}", callback_data="EXECUTE_BOTH")],[InlineKeyboardButton("Move CE Only", callback_data="MOVE_CE"),InlineKeyboardButton("Move PE Only", callback_data="MOVE_PE")],[InlineKeyboardButton("MANUAL TRADE BOTH", callback_data="MOVE_BOTH")],[InlineKeyboardButton("LIVE PNL", callback_data="LIVE_PNL")],[InlineKeyboardButton("CLOSE BOT ONLY", callback_data="CLOSE_ALL")],[InlineKeyboardButton("No Trade", callback_data="NO_TRADE")]]
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

def build_keyboard_live(atm, combined, calls, puts, spot):
    mode=selection.get("mode","MOVE_BOTH"); ideal=int(combined*2); pe_c=atm-ideal; ce_c=atm+ideal; avail=sorted(calls.keys())
    pe_list=sorted(sorted(avail, key=lambda x: abs(x-pe_c))[:7]); ce_list=sorted(sorted(avail, key=lambda x: abs(x-ce_c))[:7]); kb=[]
    curr_qty = get_current_qty_per_side()
    if mode=="MOVE_PE":
        for s in pe_list:
            ltp,_,_,_=get_ltp_live_strict(s,"P",calls,puts,spot)
            kb.append([InlineKeyboardButton(f"PE {s} @ ${ltp:.2f}"+(" YES" if selection["pe"]==s else ""), callback_data=f"SEL_PE_{s}")])
        if selection["pe"] and selection["ce"]: kb.insert(0,[InlineKeyboardButton(f"CONFIRM BOTH PE {selection['pe']} + CE {selection['ce']} QTY:{curr_qty}+{curr_qty}",callback_data="CONFIRM_BOTH_PREVIEW")])
    elif mode=="MOVE_CE":
        for s in ce_list:
            ltp,_,_,_=get_ltp_live_strict(s,"C",calls,puts,spot)
            kb.append([InlineKeyboardButton(f"CE {s} @ ${ltp:.2f}"+(" YES" if selection["ce"]==s else ""), callback_data=f"SEL_CE_{s}")])
        if selection["pe"] and selection["ce"]: kb.insert(0,[InlineKeyboardButton(f"CONFIRM BOTH PE {selection['pe']} + CE {selection['ce']} QTY:{curr_qty}+{curr_qty}",callback_data="CONFIRM_BOTH_PREVIEW")])
    else:
        for pe_s, ce_s in zip(pe_list, ce_list):
            pe_ltp,_,_,_=get_ltp_live_strict(pe_s,"P",calls,puts,spot); ce_ltp,_,_,_=get_ltp_live_strict(ce_s,"C",calls,puts,spot)
            kb.append([InlineKeyboardButton(f"PE {pe_s} ${pe_ltp:.2f}"+(" YES" if selection["pe"]==pe_s else ""), callback_data=f"SEL_PE_{pe_s}"),InlineKeyboardButton(f"CE {ce_s} ${ce_ltp:.2f}"+(" YES" if selection["ce"]==ce_s else ""), callback_data=f"SEL_CE_{ce_s}")])
        if selection["pe"] and selection["ce"]: kb.insert(0,[InlineKeyboardButton(f"CONFIRM BOTH PE {selection['pe']} + CE {selection['ce']} QTY:{curr_qty}+{curr_qty}",callback_data="CONFIRM_BOTH_PREVIEW")])
    kb.append([InlineKeyboardButton("LIVE PNL Exact", callback_data="LIVE_PNL")]); kb.append([InlineKeyboardButton("CLOSE BOT ONLY", callback_data="CLOSE_ALL")]); kb.append([InlineKeyboardButton("Cancel",callback_data="CANCEL_BOTH")])
    return kb

async def button_handler(update, context):
    global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED, LAST_SCAN_HEADER, LAST_ATM_INFO, selection, QTY, AUTO_QTY_MODE
    q=update.callback_query; await q.answer(); d=q.data
    if d in ["TIMER_ON","TIMER_OFF","TIMER_AUTO","TIMER_SETTINGS"]:
        if d=="TIMER_ON": TIMER_CONFIG["manual_override"]=True; TIMER_CONFIG["trading_active"]=True; save_config(); await q.message.reply_text("Manual ON")
        elif d=="TIMER_OFF": TIMER_CONFIG["manual_override"]=False; TIMER_CONFIG["trading_active"]=False; save_config(); await q.message.reply_text("Manual OFF")
        elif d=="TIMER_AUTO": TIMER_CONFIG["manual_override"]=None; TIMER_CONFIG["custom_range"]=None; save_config(); await q.message.reply_text("AUTO Mode")
        else:
            curr_qty = get_current_qty_per_side()
            mode_txt = "AUTO" if AUTO_QTY_MODE else "MANUAL"
            status = "ENABLED" if is_trading_allowed() else "DISABLED"
            txt=f"TIMER SETTINGS\nMode: {mode_txt}\nQTY: {curr_qty} ({curr_qty*2} Lots)\nAUTO ON: {TIMER_CONFIG['auto_on']}\nAUTO OFF: {TIMER_CONFIG['auto_off']}\nStatus: {status}"
            kb=[[InlineKeyboardButton("Timer ON", callback_data="TIMER_ON"), InlineKeyboardButton("Timer OFF", callback_data="TIMER_OFF"), InlineKeyboardButton("AUTO", callback_data="TIMER_AUTO")]]
            await q.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    if d=="DO_SCAN": await scantrade_command(update, context); return
    if d=="CLOSE_ALL": await close_command(update, context); return
    if d=="LIVE_PNL":
        total_usd,total_inr,details=get_live_pnl_from_delta_strict_margin(); spot=get_btc_spot_live()
        header = f"💰 V101 LIVE PNL\nBTC ${spot}\nMode: {'AUTO' if AUTO_QTY_MODE else 'MANUAL'} QTY: {get_current_qty_per_side()}+{get_current_qty_per_side()}\nTotal UPNL: ${total_usd:.2f} USD = {total_inr:.2f} INR\n"
        txt = header + "\n" + "\n\n".join(details) if details else f"LIVE PNL\nBTC ${spot}\nNo valid positions\nTotal UPNL: $0.00"
        await q.message.reply_text(txt); return
    if d in ["NO_TRADE","CANCEL_BOTH"]: selection["pe"]=None; selection["ce"]=None; selection["mode"]=None; await q.edit_message_text(f"{LAST_SCAN_HEADER}\n\nCancelled"); return
    try: spot,atm,cp,pp,calls,puts=get_atm_info_live()
    except Exception as e: await q.edit_message_text(f"Error {e}"); return
    pe_exist, ce_exist, _=get_positions_live()
    def get_default_strikes():
        combined=LAST_ATM_INFO.get("combined",cp+pp); ideal=int(combined*2); pe_c=atm-ideal; ce_c=atm+ideal; avail=sorted(calls.keys())
        return sorted(avail, key=lambda x: abs(x-pe_c))[0], sorted(avail, key=lambda x: abs(x-ce_c))[0], ideal
    if d in ["MOVE_CE","MOVE_PE","MOVE_BOTH"]:
        def_pe,def_ce,ideal=get_default_strikes()
        if d=="MOVE_BOTH": selection["pe"]=def_pe; selection["ce"]=def_ce
        elif d=="MOVE_PE": retained_ce=ce_exist[0] if ce_exist else def_ce; selection["pe"]=def_pe; selection["ce"]=retained_ce
        else: retained_pe=pe_exist[0] if pe_exist else def_pe; selection["pe"]=retained_pe; selection["ce"]=def_ce
        selection["mode"]=d; curr_qty=get_current_qty_per_side(); header=f"{LAST_SCAN_HEADER}\n\n{d} ATM {atm} (x2={ideal}) QTY:{curr_qty}+{curr_qty}\nSTRICT BOTH: PE {selection['pe']} | CE {selection['ce']}"
        await q.edit_message_text(header, reply_markup=InlineKeyboardMarkup(build_keyboard_live(atm,cp+pp,calls,puts,spot))); return
    if d.startswith("SEL_PE_"):
        s=int(d.replace("SEL_PE_",""))
        if selection["ce"] is None: selection["ce"]=ce_exist[0] if ce_exist else LAST_ATM_INFO.get("sug_ce")
        selection["pe"]=s; curr_qty=get_current_qty_per_side(); await q.edit_message_text(f"{LAST_SCAN_HEADER}\n\n{selection['mode']} PE {selection['pe']} | CE {selection['ce']} QTY:{curr_qty}+{curr_qty}", reply_markup=InlineKeyboardMarkup(build_keyboard_live(atm,cp+pp,calls,puts,spot))); return
    if d.startswith("SEL_CE_"):
        s=int(d.replace("SEL_CE_",""))
        if selection["pe"] is None: selection["pe"]=pe_exist[0] if pe_exist else LAST_ATM_INFO.get("sug_pe")
        selection["ce"]=s; curr_qty=get_current_qty_per_side(); await q.edit_message_text(f"{LAST_SCAN_HEADER}\n\n{selection['mode']} PE {selection['pe']} | CE {selection['ce']} QTY:{curr_qty}+{curr_qty}", reply_markup=InlineKeyboardMarkup(build_keyboard_live(atm,cp+pp,calls,puts,spot))); return
    if d in ["CONFIRM_BOTH_PREVIEW"]:
        if not selection["pe"] or not selection["ce"]:
            if LAST_ATM_INFO.get("sug_pe") and LAST_ATM_INFO.get("sug_ce"): selection["pe"]=LAST_ATM_INFO["sug_pe"]; selection["ce"]=LAST_ATM_INFO["sug_ce"]
            else: await q.edit_message_text(f"STRICT ERROR: Both required!"); return
        curr_qty=get_current_qty_per_side()
        lines=[f"{LAST_SCAN_HEADER}\n\nFINAL STRICT BOTH QTY:{curr_qty}+{curr_qty}\n"]
        if selection["pe"]:
            ltp,_,_,_=get_ltp_live_strict(selection["pe"],"P",calls,puts,spot); lines.append(f"PE {selection['pe']} @ ${ltp:.2f} -> SL ${ltp*SL_MULTIPLIER:.2f}")
        if selection["ce"]:
            ltp,_,_,_=get_ltp_live_strict(selection["ce"],"C",calls,puts,spot); lines.append(f"CE {selection['ce']} @ ${ltp:.2f} -> SL ${ltp*SL_MULTIPLIER:.2f}")
        final_text="\n".join(lines); kb=[[InlineKeyboardButton(f"YES TRADE BOTH PE {selection['pe']} + CE {selection['ce']} QTY:{curr_qty}+{curr_qty}", callback_data="EXECUTE_BOTH")]]
        kb.append([InlineKeyboardButton("Back", callback_data=selection["mode"]), InlineKeyboardButton("Cancel", callback_data="CANCEL_BOTH")])
        await q.edit_message_text(final_text, reply_markup=InlineKeyboardMarkup(kb)); return
    if d in ["EXECUTE_BOTH"]:
        if not selection["pe"] or not selection["ce"]:
            if LAST_ATM_INFO.get("sug_pe") and LAST_ATM_INFO.get("sug_ce"):
                selection["pe"]=LAST_ATM_INFO["sug_pe"]; selection["ce"]=LAST_ATM_INFO["sug_ce"]
            else: await q.edit_message_text(f"STRICT ERROR: Need BOTH"); return
        curr_qty=get_current_qty_per_side()
        mode_txt="AUTO" if AUTO_QTY_MODE else "MANUAL"
        txt=f"⚠️ QTY CONFIRMATION ({mode_txt})\n\nPE {selection['pe']} + CE {selection['ce']}\n\nQTY: {curr_qty} Call + {curr_qty} Put = {curr_qty*2} Lots Total\nSize: {abs(get_lot_size_for_trade()):.4f} BTC\nSame Qty Both Side ✅\n\nMaathanumna /qty auto | /qty 25\nReady na YES click pannunga"
        kb=[[InlineKeyboardButton(f"✅ YES TRADE {curr_qty}+{curr_qty} ({abs(get_lot_size_for_trade()):.4f} BTC)", callback_data="FINAL_EXECUTE")],[InlineKeyboardButton("❌ Cancel", callback_data="CANCEL_BOTH")]]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb)); return
    if d in ["FINAL_EXECUTE"]:
        if not selection["pe"] or not selection["ce"]: await q.edit_message_text(f"STRICT ERROR"); return
        if not is_trading_allowed(): await q.edit_message_text(f"TIMER BLOCKED"); return
        lot_size=get_lot_size_for_trade()
        curr_qty=get_current_qty_per_side()
        try:
            pe_ltp,pe_pid,_,_=get_ltp_live_strict(selection["pe"],"P",calls,puts,spot)
            ce_ltp,ce_pid,_,_=get_ltp_live_strict(selection["ce"],"C",calls,puts,spot)
            cb, pids = close_bot_positions_only(); time.sleep(0.8)
            close_sl_only_for_bot_products(pids); time.sleep(0.5)
            place_order_live_with_retry(pe_pid, lot_size, "sell"); time.sleep(0.6)
            add_bot_product(pe_pid)
            place_order_live_with_retry(ce_pid, lot_size, "sell"); time.sleep(0.5)
            add_bot_product(ce_pid)
            place_sl_live(pe_pid, lot_size, pe_ltp); place_sl_live(ce_pid, lot_size, ce_ltp)
            global SMART_ENABLED, COLLECTED_COMBINED, SMART_SL_COMBINED
            COLLECTED_COMBINED=pe_ltp+ce_ltp; SMART_ENABLED=True; SMART_SL_COMBINED=0
            await q.edit_message_text(f"BOTH SUCCESS V101 {curr_qty}+{curr_qty}\nPE {selection['pe']} @ ${pe_ltp:.2f}\nCE {selection['ce']} @ ${ce_ltp:.2f}\nSize {abs(lot_size):.4f} BTC = {curr_qty} Lots Per Side\nCollected ${COLLECTED_COMBINED:.2f}\nMode: {'AUTO' if AUTO_QTY_MODE else 'MANUAL'} Same Qty ✅")
        except Exception as e: await q.edit_message_text(f"FAILED: {e}")
        selection["pe"]=None; selection["ce"]=None; selection["mode"]=None; return

async def post_init(app):
    try:
        spot=get_btc_spot_live()
        curr_qty=get_current_qty_per_side()
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"V101 AUTO TRADE TIMER ✅\nBTC ${spot}\nMode: {'AUTO' if AUTO_QTY_MODE else 'MANUAL'}\nQTY: {curr_qty}+{curr_qty} = {curr_qty*2} Lots\nBase: 50 Lots = {FUNDS_PER_50_LOTS}$\n/qty auto | /qty 25\nTimer: ON=Trade OFF=Close")
    except: pass

def main():
    req=HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, write_timeout=60.0, pool_timeout=60.0)
    app=Application.builder().token(TELEGRAM_BOT_TOKEN).request(req).build()
    app.add_handler(CommandHandler("start",start_command))
    app.add_handler(CommandHandler("scantrade",scantrade_command))
    app.add_handler(CommandHandler("livepnl",livepnl_command))
    app.add_handler(CommandHandler("pnl",livepnl_command))
    app.add_handler(CommandHandler("close",close_command))
    app.add_handler(CommandHandler("closetrade",close_command))
    app.add_handler(CommandHandler("closeall",close_command))
    app.add_handler(CommandHandler("cleanall",cleanall_command))
    app.add_handler(CommandHandler("qty",qty_command))
    app.add_handler(CommandHandler("setontime",setontime_command))
    app.add_handler(CommandHandler("setofftime",setofftime_command))
    app.add_handler(CommandHandler("timer",timer_command))
    app.add_handler(CommandHandler("timersettings",timersettings_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.post_init=post_init
    app.job_queue.run_repeating(smart_trail_job, interval=60, first=10, job_kwargs={'misfire_grace_time':60})
    app.job_queue.run_repeating(individual_sl_monitor_job, interval=60, first=12, job_kwargs={'misfire_grace_time':60})
    app.job_queue.run_repeating(timer_auto_job, interval=60, first=10, job_kwargs={'misfire_grace_time':60})
    print(f"V101 AUTO TRADE TIMER - READY")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
