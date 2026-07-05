import os
import re
import logging
import sqlite3
import asyncio
import time
import hashlib
from html import escape
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Load Environment Config
load_dotenv()

# Setup Advanced Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================================================
# SYSTEM CONSTANTS & STATES MANAGER
# =========================================================
STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
STATUS_PENDING_REVIEW = "PENDING_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED = "EXPIRED"

# =========================================================
# CRITICAL STARTUP VALIDATION ENGINE
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
UPI_ID = os.getenv("UPI_ID", "").strip()
ACCOUNT_NAME = os.getenv("ACCOUNT_NAME", "").strip()

if not BOT_TOKEN: raise ValueError("CRITICAL ERROR: 'BOT_TOKEN' is missing in .env")
if not UPI_ID: raise ValueError("CRITICAL ERROR: 'UPI_ID' is missing in .env")
if not ACCOUNT_NAME: raise ValueError("CRITICAL ERROR: 'ACCOUNT_NAME' is missing in .env")

try:
    ADMINS = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
    if not ADMINS: raise ValueError
except Exception:
    raise ValueError("CRITICAL ERROR: 'ADMINS' missing or invalid format in .env")

try:
    ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
    if ADMIN_GROUP_ID == 0: raise ValueError
except Exception:
    raise ValueError("CRITICAL ERROR: 'ADMIN_GROUP_ID' missing or invalid in .env")

SUPPORT_USERNAME = "USDT_No1_BOT"
BOT_NAME = "USDT FARM"
DB_FILE = "orders.db"

# Deployment Debugging Infrastructure Logs
logger.info(f"Bot started: {BOT_NAME}")
logger.info(f"🚀 Loaded {len(ADMINS)} admins successfully from configuration matrix.")
logger.info(f"📊 Admin Compliance Group ID set to: {ADMIN_GROUP_ID}")

LIMITS = {"MIN": 150, "MAX": 10000}
USDT_PRICE = 100

QR_URL = "https://graph.org/file/b8c78cd82c1f361c90921-e36f6a93f11b1b62a4.jpg"
LOGO_URL = "https://graph.org/file/f34820a99c1daa95ca35b-c1ea805f3bb2111f6e.jpg"
FOOTER_TAG = "⚡ <i>Powered by Usdt Farm Ecosystem • Secured Node</i>"

# Validations Regex
RE_EVM = r"^0x[a-fA-F0-9]{40}$"
RE_UTR = r"^\d{12,22}$"  # Extended 12 to 22-Digit Format for Dynamic Banking Lifecycles

# =========================================================
# CRYPTOGRAPHIC TRC20 PARSER 
# =========================================================
def verify_trc20_address(address: str) -> bool:
    """Performs Base58Check decode structural validation for TRON address geometry."""
    if not re.match(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", address):
        return False
    
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    try:
        num = 0
        for char in address:
            num = num * 58 + alphabet.index(char)
        
        combined_bytes = num.to_bytes(25, byteorder='big')
        payload = combined_bytes[:-4]
        checksum = combined_bytes[-4:]
        
        hash1 = hashlib.sha256(payload).digest()
        hash2 = hashlib.sha256(hash1).digest()
        
        return hash2[:4] == checksum
    except Exception:
        return False

# =========================================================
# CONCURRENCY-SAFE ISOLATED DATABASE MANAGER
# =========================================================
def get_db_connection():
    """Returns sqlite3 connection with strict thread mapping safety and timeout configurations."""
    conn = sqlite3.connect(
        DB_FILE, 
        timeout=30.0
    )
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")      
        conn.execute("PRAGMA synchronous=NORMAL;") 
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            usdt REAL,
            network TEXT,
            wallet TEXT,
            amount INTEGER,
            escrow INTEGER,
            escrow_charge INTEGER,
            billing TEXT,
            status TEXT,
            timestamp INTEGER,
            screenshot TEXT DEFAULT '',
            utr TEXT DEFAULT ''
        )
        """)  
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_utr_unique ON orders(utr) WHERE utr != '';")
        
        # High-Performance Indexes for Large Volume Optimization
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);")
        
        conn.commit()

init_db()

# =========================================================
# PERSISTENT EXPIRE LIFECYCLE ENGINE
# =========================================================
async def async_expire_worker(order_id: int, application, delay: float = 1800.0):
    """Asynchronous background scheduler handling persistent TTL expiration verification."""
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            user_row = cursor.fetchone()
            if not user_row:
                return  
            user_id = user_row[0]

            # 100% Atomic Expiry Check
            cursor.execute(
                """
                UPDATE orders 
                SET status=? 
                WHERE order_id=? 
                AND status=?
                """, 
                (STATUS_EXPIRED, order_id, STATUS_PENDING_PAYMENT)
            )
            conn.commit()
            
            if cursor.rowcount == 0:
                return 

            await application.bot.send_message(
                chat_id=user_id,
                text=f"⏰ <b>ORDER EXPIRED (#_{order_id})</b>\n\nYour 30-minute allocation time window has completed. This invoice is closed. Please create a new invoice.",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Async expiration worker anomaly for Order #{order_id}: {e}")

async def post_init_recovery_hook(application) -> None:
    """Official PTB Framework Native Lifecycle Hook to securely restore tasks after boot/restart."""
    try:
        current_time = int(time.time())
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT order_id, timestamp FROM orders WHERE status=?", (STATUS_PENDING_PAYMENT,))
            pending_orders = cursor.fetchall()
            
        for order_id, timestamp in pending_orders:
            elapsed_time = current_time - timestamp
            remaining_ttl = 1800.0 - elapsed_time
            
            if remaining_ttl <= 0:
                application.create_task(async_expire_worker(order_id, application, delay=0))
            else:
                application.create_task(async_expire_worker(order_id, application, delay=remaining_ttl))
        print(f"🌞 [RECOVERY MODULE COMPLETED] Native lifecycle synced {len(pending_orders)} active allocation tasks.")
    except Exception as e:
        logger.error(f"Critical error executed inside startup recovery chain: {e}")

def price_calculator(usdt: float) -> int:
    return int(round(usdt * USDT_PRICE))

# =========================================================
# USER INTERFACE HANDLERS & BOT CONTROLS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_time = time.time()
    last_req = context.user_data.get("last_request_time", 0)
    if current_time - last_req < 2.0:
        return await update.message.reply_text("🚨 <b>Rate Limit!</b> Please slow down your requests.", parse_mode="HTML")
    context.user_data["last_request_time"] = current_time

    keyboard = [
        [InlineKeyboardButton("💳 Instant Buy USDT", callback_data="BUY")],
        [InlineKeyboardButton("🛡️ Secure Escrow Deal", callback_data="ESCROW")],
        [InlineKeyboardButton("💬 Official Support", url=f"tg://openmessage?user_id=1888507338")]
    ]

    caption = f"""
✨ <b>WELCOME TO {BOT_NAME}</b> ✨
━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 <i>India's Most Reliable & Advanced Crypto OTC Platform</i>

⚡ <b>Engine Framework:</b>
├─ Anti-Fraud Structural Base58 Check
├─ Persistent Multi-State Tracking Matrix
└─ High-Throughput Concurrency Support

📊 <b>Live OTC Index:</b>
├─ <b>Rate:</b> ₹{USDT_PRICE} INR / USDT
├─ <b>Minimum Order:</b> {LIMITS['MIN']} USDT
└─ <b>Maximum Order:</b> {LIMITS['MAX']} USDT

🛡️ <b>Escrow Fee Protection:</b> ₹0 (FREE)
━━━━━━━━━━━━━━━━━━━━━━━━━━
👇 <i>Select a system entry-point from options below:</i>

{FOOTER_TAG}
"""
    await update.message.reply_photo(
        photo=LOGO_URL,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data.update({"stage": "await_amount", "escrow": 0})
    await q.message.reply_text(
        f"📥 <b>[DIRECT SETTLEMENT PROTOCOL]</b>\n\nEnter the exact amount of <b>USDT</b> to purchase:\n"
        f"<code>Bounds: {LIMITS['MIN']} - {LIMITS['MAX']} USDT</code>",
        parse_mode="HTML"
    )

async def callback_escrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data.update({"stage": "await_amount", "escrow": 1})
    await q.message.reply_text(
        f"🛡️ <b>[ESCROW PROTECTION NODE ACTIVATED]</b>\n\nEnter the asset transaction volume in <b>USDT</b>:\n"
        f"<code>Bounds: {LIMITS['MIN']} - {LIMITS['MAX']} USDT</code>",
        parse_mode="HTML"
    )

# =========================================================
# STATE MANIFEST LOOP & BUSINESS FLOW CONTROL
# =========================================================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    stage = context.user_data.get("stage")
    
    current_time = time.time()
    last_req = context.user_data.get("last_request_time", 0)
    if current_time - last_req < 1.0: return
    context.user_data["last_request_time"] = current_time

    # STAGE 1: AMOUNT MANAGEMENT
    if stage == "await_amount":
        try:
            usdt = float(txt)
        except ValueError:
            return await update.message.reply_text("❌ <b>Formatting Error:</b> Numerical decimal or integers digits only required.", parse_mode="HTML")

        if usdt < LIMITS['MIN'] or usdt > LIMITS['MAX']:
            return await update.message.reply_text(f"🚨 <b>Boundary Breach!</b> Range limit is <code>{LIMITS['MIN']}-{LIMITS['MAX']}</code> USDT.", parse_mode="HTML")

        amount = price_calculator(usdt)
        
        billing = f"""
🧾 <b>SYSTEM TRANSACTION INVOICE</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Asset Class:</b> USDT
📈 <b>Volume:</b> {usdt} units
💵 <b>Exchange Reference:</b> ₹{USDT_PRICE} INR
💸 <b>Base Value:</b> ₹{amount}
🛡️ <b>Escrow Coverage:</b> ₹0
━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 <b>TOTAL LIQUID PAYABLE:</b> <code>₹{amount}</code>
━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        context.user_data.update({
            "usdt": usdt, "amount": amount, "billing": billing, "stage": "choose_network"
        })

        keyboard = [
            [InlineKeyboardButton("🌐 TRC20", callback_data="NET:TRC20"), InlineKeyboardButton("🟡 BEP20", callback_data="NET:BEP20")],
            [InlineKeyboardButton("🔵 ERC20", callback_data="NET:ERC20")]
        ]
        await update.message.reply_text(
            f"📊 <b>LIQUIDITY PIPELINE PREPARED</b>\n\n"
            f"├─ <b>Target Asset:</b> {usdt} USDT\n"
            f"├─ <b>INR Valuation:</b> ₹{amount}\n"
            f"└─ <b>Escrow State:</b> {'Active ✅' if context.user_data.get('escrow') else 'Inactive ❌'}\n\n"
            f"👇 <i>Specify processing Settlement Blockchain Network:</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    # STAGE 2: WALLET DEPLOYMENT
    if stage == "await_wallet":
        sanitized_wallet = escape(txt)
        network = context.user_data.get("network")
        
        is_valid = False
        if network == "TRC20":
            is_valid = verify_trc20_address(sanitized_wallet)
        elif network in ["ERC20", "BEP20"]:
            is_valid = bool(re.match(RE_EVM, sanitized_wallet))
            
        if not is_valid:
            return await update.message.reply_text(
                f"🚨 <b>CRYPTOGRAPHIC COMPLIANCE FAULT</b>\n\nThe input structure fails standard cryptographic compliance for the <b>{network}</b> architecture. Provide a genuine, verified hash string address.",
                parse_mode="HTML"
            )

        usdt = context.user_data["usdt"]
        amount = context.user_data["amount"]
        billing = context.user_data["billing"]
        escrow = context.user_data.get("escrow", 0)

        # Null User Profile Crash Proofing Guard via Strict Type String Casts Fallback Logic (Issue 1 Fix)
        raw_username = (
            update.effective_user.username 
            or update.effective_user.first_name 
            or str(update.effective_user.id)
        )
        truncated_username = raw_username[:100]

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders(user_id, username, usdt, network, wallet, amount, escrow, escrow_charge, billing, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                update.effective_user.id,
                truncated_username,
                usdt, network, sanitized_wallet, amount, escrow, 0, billing, STATUS_PENDING_PAYMENT, int(time.time())
            ))
            conn.commit()
            order_id = cursor.lastrowid

        context.application.create_task(async_expire_worker(order_id, context.application))
        context.user_data.clear()

        caption = f"""
📦 <b>ORDER PRODUCED ➔ WAITING FOR PAYMENT</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>ORDER IDENTIFIER:</b> <code>#{order_id}</code>
🔒 <b>PROTECTION STYLE:</b> {'ESCROW BALANCED' if escrow else 'DIRECT SETTLEMENT'}

💎 <b>SPECIFICATIONS:</b>
├─ <b>Liquidity Value:</b> {usdt} USDT
├─ <b>Target Infrastructure:</b> {network}
└─ <b>Payout Target Node:</b> <code>{sanitized_wallet}</code>

{billing}
🏛️ <b>BANKING TRANSFER GATEWAY DETAILS</b>
👤 <b>Holder Account Name:</b> {ACCOUNT_NAME}
🏧 <b>VPA Core Address:</b> <code>{UPI_ID}</code>
━━━━━━━━━━━━━━━━━━━━━━━━━━
👉 <b>HOW TO COMPREHEND TRANSACTION:</b>
1️⃣ Scan the QR / copy UPI ID above and execute the payment.
2️⃣ Click the button below to link your 12-22 digit transaction <b>UTR</b>.
3️⃣ Send your dynamic banking application image receipt.

⚠️ <i>Invoice absolute timeout set to 30 minutes.</i>
"""
        keyboard = [[InlineKeyboardButton("🎯 Link UTR & Upload Proof", callback_data=f"USER:SUBMIT:{order_id}")]]
        await update.message.reply_photo(photo=QR_URL, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # STAGE 3: UTR LINKING INPUT
    if stage == "await_utr_explicit":
        utr = escape(txt)
        if not re.match(RE_UTR, utr):
            return await update.message.reply_text("❌ <b>Verification Discrepancy:</b> UPI Network rules mandate a strict 12 to 22-digit numerical sequence. Re-enter correctly.", parse_mode="HTML")

        target_order_id = context.user_data.get("active_submission_order_id")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT status FROM orders WHERE order_id=?", (target_order_id,))
            order_row = cursor.fetchone()
            if not order_row or order_row[0] != STATUS_PENDING_PAYMENT:
                return await update.message.reply_text("⏰ <b>Allocation State Closed:</b> This order layout has expired or shifted states.", parse_mode="HTML")

            try:
                cursor.execute(
                    """
                    UPDATE orders 
                    SET utr=? 
                    WHERE order_id=? 
                    AND user_id=? 
                    AND status=?
                    """, 
                    (utr, target_order_id, update.effective_user.id, STATUS_PENDING_PAYMENT)
                )
                conn.commit()
                rows_affected = cursor.rowcount
            except sqlite3.IntegrityError:
                return await update.message.reply_text("🚨 <b>MUTATION REUSE THREAT ALERT:</b> Unique database index rejected this duplicate UTR code.", parse_mode="HTML")

        if rows_affected == 0:
            return await update.message.reply_text("⏰ <b>Allocation State Closed:</b> Order does not exist, ownership mismatched, or session has already expired.", parse_mode="HTML")

        context.user_data["stage"] = "await_screenshot_explicit"
        await update.message.reply_text(
            f"✅ <b>UTR {utr} BOUND TO INSTANCE #{target_order_id}</b>\n\n"
            "Now, upload the <b>Payment Screenshot / Receipt Image</b> directly here to pass compliance mapping:",
            parse_mode="HTML"
        )
        return

# =========================================================
# CALLBACK ROUTING CORE ENGINE
# =========================================================
async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "BUY": return await callback_buy(update, context)
    if q.data == "ESCROW": return await callback_escrow(update, context)

    if q.data.startswith("NET:"):
        context.user_data.update({"network": q.data.split(":")[1], "stage": "await_wallet"})
        await q.message.reply_text(
            "🏦 <b>TARGET BLOCKCHAIN INFRASTRUCTURE</b>\n\nProvide your destination public address hash mapping:\n"
            "⚠️ <i>Verify string chain matches chosen standard perfectly.</i>",
            parse_mode="HTML"
        )
        return

    if q.data.startswith("USER:SUBMIT:"):
        order_id = int(q.data.split(":")[2])
        caller_id = q.from_user.id
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, status, screenshot FROM orders WHERE order_id=?", (order_id,))
            row = cursor.fetchone()
            
        if not row:
            return await q.message.reply_text("❌ <b>Not Found:</b> Target order layout trace missing.", parse_mode="HTML")
        
        if int(row[0]) != caller_id:
            return await q.answer("🔒 Security Exception: Access Denied. You are not the initiator of this transaction token.", show_alert=True)
            
        if row[1] != STATUS_PENDING_PAYMENT:
            return await q.message.reply_text(f"❌ <b>State Intercepted:</b> This order session is closed. State status: [{row[1]}].", parse_mode="HTML")
        if row[2] != "":
            return await q.message.reply_text("🚨 <b>Fraud Shield Prevent:</b> Evidence arrays are already tied to this node.", parse_mode="HTML")

        context.user_data.update({"stage": "await_utr_explicit", "active_submission_order_id": order_id})
        await q.message.reply_text(f"📝 <b>ORDER TRACKING INITIALIZED FOR #{order_id}</b>\n\nPlease submit the 12-22 digit bank reference <b>UTR number</b> first:", parse_mode="HTML")
        return

    if q.data.startswith("ADMIN:"):
        try:
            action, order_id_str = q.data.split(":")[1:]
            order_id = int(order_id_str)
        except Exception:
            logger.error("Intercepted malformed admin callback signature attempt.")
            return

        # Explicit White-List Sanity Guard Targeting Forged Multi-State Interceptions Actions (Issue 2 Fix)
        if action not in ("APPROVE", "CANCEL"):
            logger.warning(f"Malicious or Unknown Admin Payload Action execution dropped: {action}")
            return

        if q.from_user.id not in ADMINS:
            return await q.answer("🔒 Security Exception: Access Credentials Revoked.", show_alert=True)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            target_status = STATUS_APPROVED if action == "APPROVE" else STATUS_CANCELLED
            cursor.execute(
                "UPDATE orders SET status=? WHERE order_id=? AND status=?", 
                (target_status, order_id, STATUS_PENDING_REVIEW)
            )
            conn.commit()
            
            if cursor.rowcount == 0:
                return await q.answer("⚠️ System Alert: This order instance has already been processed or closed by another administrator.", show_alert=True)

            cursor.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            uid = cursor.fetchone()[0]

            admin_identity = f"@{q.from_user.username}" if q.from_user.username else q.from_user.first_name

            if action == "APPROVE":
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"✅ <b>ASSET DISBURSEMENT COMPLETED</b>\n\nYour order invoice <b>#{order_id}</b> has cleared auditing loops. Liquidity parameters released to your crypto vault address.",
                        parse_mode="HTML"
                    )
                except Exception as e: logger.error(f"Failed to alert user {uid}: {e}")

                try:
                    await q.message.edit_caption(
                        caption=f"✅ <b>LEDGER NODE SEALED [APPROVED]</b>\n\n├─ <b>Order Reference:</b> #{order_id}\n└─ <b>Verified Compliance Auditor:</b> {admin_identity}",
                        parse_mode="HTML"
                    )
                except Exception as ex: logger.error(f"Caption edit execution error wrap: {ex}")

            elif action == "CANCEL":
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"❌ <b>TRANSACTION DISCARDED / REJECTED</b>\n\nOrder instance <b>#{order_id}</b> failed to satisfy verification checks. Ledger balance unchanged.\n\n📞 <b>Support Center Core:</b> @{SUPPORT_USERNAME}",
                        parse_mode="HTML"
                    )
                except Exception as e: logger.error(f"Failed to alert user {uid}: {e}")

                try:
                    await q.message.edit_caption(
                        caption=f"🛑 <b>LEDGER NODE SEALED [VOIDED/CANCELLED]</b>\n\n├─ <b>Order Reference:</b> #{order_id}\n└─ <b>Voiding Compliance Auditor:</b> {admin_identity}",
                        parse_mode="HTML"
                    )
                except Exception as ex: logger.error(f"Caption edit execution error wrap: {ex}")

# =========================================================
# PROOF SNAPSHOT RECEIVER ENGINE
# =========================================================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stage = context.user_data.get("stage")
    target_order_id = context.user_data.get("active_submission_order_id")

    if stage != "await_screenshot_explicit" or not target_order_id:
        return await update.message.reply_text("❌ <b>Flow Violation:</b> Please tap the 'Link UTR & Upload Proof' button on your order invoice before uploading your snapshot receipt.", parse_mode="HTML")

    file_id = update.message.photo[-1].file_id

    # Ironclad Session Ownership Lock Validation Injected into Atomic Status Matrix (Issue 3 Fix)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE orders 
            SET screenshot=?, status=? 
            WHERE order_id=? 
            AND user_id=?
            AND screenshot='' 
            AND status=?
            """, 
            (file_id, STATUS_PENDING_REVIEW, target_order_id, user.id, STATUS_PENDING_PAYMENT)
        )
        conn.commit()
        rows_affected = cursor.rowcount

    if rows_affected == 0:
        return await update.message.reply_text("🚨 <b>Double Submission Shield:</b> Proof vectors are already locked or transmission failed.", parse_mode="HTML")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT usdt, network, wallet, amount, escrow, utr FROM orders WHERE order_id=?", (target_order_id,))
        row = cursor.fetchone()
        
    if not row:
        logger.error(f"CRITICAL DISCREPANCY: Order #{target_order_id} disappeared unexpectedly from database map context during screenshot binding.")
        return await update.message.reply_text("❌ <b>Critical Data Anomaly:</b> This localized data block could not be extracted from database memory registers.", parse_mode="HTML")

    usdt, network, wallet, amount, escrow, utr = row
    context.user_data.clear()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE RELEASE", callback_data=f"ADMIN:APPROVE:{target_order_id}")],
        [InlineKeyboardButton("❌ VOID / DISMISS TRANSACTION", callback_data=f"ADMIN:CANCEL:{target_order_id}")]
    ])

    client_title = f"@{user.username}" if user.username else user.first_name
    admin_caption = f"""
📥 <b>NEW PAYLOAD EVIDENCE REVIEWS INBOUND</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>Audit Manifest Target:</b> <code>#{target_order_id}</code>
👤 <b>Client Passport:</b> {client_title} (<code>{user.id}</code>)

💎 <b>SPECIFICATIONS DECLARED:</b>
├─ <b>Volume Payload:</b> {usdt} USDT
├─ <b>Target Infrastructure Chain:</b> {network}
└─ <b>Client Vault Address:</b> <code>{wallet}</code>

💵 <b>FINANCIAL EVIDENCE COUPLING:</b>
├─ <b>System Invoiced Bill Amount:</b> ₹{amount} INR
├─ <b>Target Gateway VPA Address:</b> {UPI_ID}
└─ <b>Declared Linked UTR Reference:</b> <code>{utr}</code>

🛡️ <b>Structural OTC Core Protocol:</b> {'Secure Escrow Node Balance' if escrow else 'Direct Balance Settlement'}
━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 <b>MANUAL VERIFICATION MANDATE NOTE:</b>
<i>The system status is updated to <b>PENDING_REVIEW</b>. This invoice cannot be auto-expired. Cross-verify with your physical bank account before executing programmatic release commands.</i>
"""
    await context.bot.send_photo(
        chat_id=ADMIN_GROUP_ID, photo=file_id, caption=admin_caption,
        parse_mode="HTML", reply_markup=keyboard
    )

    await update.message.reply_text(
        "⚡ <b>TRANSACTION EVIDENCE COMMITTED TO LOGS</b>\n\nYour proof vectors have safe-landed inside our auditing queue.\n"
        "⌛ <i>Average verification loop wait time: 1-5 Minutes. Notifications stream automatically.</i>",
        parse_mode="HTML"
    )

# =========================================================
# GLOBAL SYSTEM PROTECTION INTERCEPTOR FAILSAFE
# =========================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Failsafe Protocol caught unhandled exception exception loop:", exc_info=context.error)

# =========================================================
# MAIN REVOLUTION ENGINE EXECUTION INTERFACE
# =========================================================
def main():
    # Bridge start-up lifecycle tasks synchronously via Official Framework Native Lifecycle Hooks Engine
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init_recovery_hook).build()

    # Register Engine Modules Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    app.add_error_handler(error_handler)

    print(f"🌞 [ENTERPRISE SECURE PRODUCTION CORE ON] Running {BOT_NAME} System Engine safely.")
    app.run_polling()

if __name__ == "__main__":
    main()
