import os, json, logging, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from mcrcon import MCRcon

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zerux-donat")

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
RCON_HOST = os.environ["RCON_HOST"]
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ["RCON_PASSWORD"]
PAYMENT_TEXT = os.environ.get("PAYMENT_TEXT", "Admin karta ma’lumotini yuborishini kuting.")
SERVER_NAME = os.environ.get("SERVER_NAME", "ZERUXSMP")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "NOUSER1U").lstrip("@")
PRODUCTS = json.load(open("products.json", encoding="utf-8"))
orders = {}
next_order_id = 1
admin_waiting_card = {}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Donat do‘koni", callback_data="shop")],
        [InlineKeyboardButton("📋 Buyurtmalarim", callback_data="myorders"),
         InlineKeyboardButton("ℹ️ Admin / To‘lov", callback_data="payment")]
    ])

def shop_keyboard():
    rows = [[InlineKeyboardButton(f"{p['name']} — {p['price']}", callback_data=f"product:{p['id']}")] for p in PRODUCTS]
    rows.append([InlineKeyboardButton("⬅️ Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⛏️ {SERVER_NAME} DONAT BOT\\n\\nMahsulot tanlang, Minecraft nickingizni kiriting. Bot admin @{ADMIN_USERNAME} orqali karta ma’lumotini yuboradi. To‘lovdan keyin chek rasmini yuborasiz.",
        reply_markup=main_menu()
    )

async def shop_text(q):
    await q.edit_message_text("🛒 Donat do‘koni — mahsulotni tanlang:", reply_markup=shop_keyboard())

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_order_id
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "home":
        await q.edit_message_text(f"⛏️ {SERVER_NAME} DONAT BOT", reply_markup=main_menu())
    elif data == "shop":
        await shop_text(q)
    elif data == "payment":
        await q.edit_message_text(
            f"💳 To‘lov uchun admin: @{ADMIN_USERNAME}\\nMahsulot tanlab buyurtma yuboring — admin karta raqamini bot orqali yuboradi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bosh menyu", callback_data="home")]])
        )
    elif data == "myorders":
        user_orders = [o for o in orders.values() if o["telegram_id"] == q.from_user.id]
        text = "Sizda hozircha buyurtma yo‘q." if not user_orders else "📋 Buyurtmalaringiz:\\n\\n" + "\\n".join(
            f"#{o['id']} — {o['product_name']} — {o['status']}" for o in user_orders[-10:]
        )
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bosh menyu", callback_data="home")]]))
    elif data.startswith("product:"):
        product_id = data.split(":", 1)[1]
        product = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if not product:
            await q.edit_message_text("Mahsulot topilmadi.")
            return
        context.user_data["selected_product"] = product_id
        context.user_data["awaiting_nick"] = True
        await q.edit_message_text(
            f"Tanlandi: {product['name']}\\nNarxi: {product['price']}\\n\\nMinecraft nickingizni yuboring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Bekor qilish", callback_data="shop")]])
        )
    elif data.startswith("sendcard:"):
        if q.from_user.id != ADMIN_ID:
            await q.answer("Faqat admin ishlata oladi.", show_alert=True)
            return
        oid = int(data.split(":", 1)[1])
        order = orders.get(oid)
        if not order:
            await q.answer("Buyurtma topilmadi.", show_alert=True)
            return
        admin_waiting_card[ADMIN_ID] = oid
        await q.message.reply_text(f"Buyurtma #{oid} uchun karta raqamini va kerakli to‘lov izohini shu chatga bitta xabar qilib yuboring. Men uni xaridorga yuboraman.")
    elif data.startswith("paid:"):
        oid = int(data.split(":", 1)[1])
        order = orders.get(oid)
        if not order or order["telegram_id"] != q.from_user.id:
            await q.answer("Bu buyurtma sizniki emas.", show_alert=True)
            return
        order["status"] = "Chek kutilmoqda"
        await q.edit_message_text(f"✅ To‘lov qilganingizni belgiladingiz. Endi chek rasmini shu botga yuboring. Buyurtma #{oid}.")
    elif data.startswith("approve:") or data.startswith("reject:"):
        if q.from_user.id != ADMIN_ID:
            await q.answer("Faqat admin tasdiqlashi mumkin.", show_alert=True)
            return
        action, order_id = data.split(":")
        order = orders.get(int(order_id))
        if not order:
            await q.edit_message_caption("Buyurtma topilmadi.")
            return
        if order["status"] != "Chek admin tekshiruvida":
            await q.answer("Avval o‘yinchi chek yuborishi kerak.", show_alert=True)
            return
        if action == "reject":
            order["status"] = "Rad etildi"
            await q.edit_message_caption((q.message.caption or "") + "\\n\\n❌ Admin buyurtmani rad etdi.")
            await context.bot.send_message(order["telegram_id"], f"❌ #{order['id']} buyurtmangiz rad etildi. @{ADMIN_USERNAME} bilan bog‘laning.")
            return
        try:
            for cmd in order["commands"]:
                safe_cmd = cmd.format(player=order["minecraft_nick"])
                if safe_cmd.startswith("/") or "\\n" in safe_cmd or "\\r" in safe_cmd:
                    raise ValueError("Noto‘g‘ri server buyrug‘i")
                await asyncio.to_thread(run_rcon, safe_cmd)
            order["status"] = "Berildi"
            await q.edit_message_caption((q.message.caption or "") + "\\n\\n✅ Tasdiqlandi va serverga berildi.")
            await context.bot.send_message(order["telegram_id"], f"✅ To‘lov tasdiqlandi! {order['product_name']} {order['minecraft_nick']} akkauntiga berildi. Buyurtma #{order['id']}.")
        except Exception:
            log.exception("RCON command failed for order %s", order["id"])
            await q.answer("RCON xatosi. Railway loglarini tekshiring.", show_alert=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_order_id
    user = update.effective_user
    text = (update.message.text or "").strip()

    # Admin's card number/message is forwarded to the selected customer.
    if user.id == ADMIN_ID and ADMIN_ID in admin_waiting_card:
        oid = admin_waiting_card.pop(ADMIN_ID)
        order = orders.get(oid)
        if not order:
            await update.message.reply_text("Buyurtma topilmadi.")
            return
        order["status"] = "Karta yuborildi"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ To‘lov qildim", callback_data=f"paid:{oid}")]])
        await context.bot.send_message(
            order["telegram_id"],
            f"💳 TO‘LOV MA’LUMOTI — buyurtma #{oid}\\n"
            f"Mahsulot: {order['product_name']}\\nNarx: {order['price']}\\n"
            f"Karta / to‘lov ma’lumoti:\\n{text}\\n\\n"
            f"To‘lovni amalga oshirgach, quyidagi tugmani bosing va chek rasmini yuboring.",
            reply_markup=keyboard
        )
        await update.message.reply_text(f"✅ Karta ma’lumoti buyurtma #{oid} egasiga yuborildi.")
        return

    if context.user_data.get("awaiting_nick"):
        if not (3 <= len(text) <= 16) or not text.replace("_", "").isalnum():
            await update.message.reply_text("Nick noto‘g‘ri. 3–16 belgi, faqat harf, raqam va _ ishlating.")
            return
        product_id = context.user_data.get("selected_product")
        product = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if not product:
            context.user_data.clear()
            await update.message.reply_text("Mahsulot topilmadi. /start ni bosing.")
            return
        oid = next_order_id
        next_order_id += 1
        order = {
            "id": oid, "telegram_id": user.id,
            "username": user.username or user.full_name,
            "minecraft_nick": text, "product_name": product["name"],
            "price": product["price"], "commands": product["commands"],
            "status": "Karta kutilmoqda"
        }
        orders[oid] = order
        context.user_data["awaiting_nick"] = False
        context.user_data.pop("selected_product", None)
        caption = (f"🛒 DONAT BUYURTMASI #{oid}\\n"
                   f"Telegram: @{order['username']} (ID {order['telegram_id']})\\n"
                   f"Minecraft nick: {text}\\nMahsulot: {product['name']}\\n"
                   f"Narx: {product['price']}\\nHolat: Karta kutilmoqda")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Karta raqamini yuborish", callback_data=f"sendcard:{oid}")]])
        await context.bot.send_message(ADMIN_ID, caption, reply_markup=kb)
        await update.message.reply_text(f"✅ Buyurtma #{oid} adminga yuborildi. @{ADMIN_USERNAME} karta ma’lumotini yuborishini kuting.")
        return
    await update.message.reply_text("Menyudan foydalaning: /start")

async def on_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("receipt_order_id"):
        # Find the user's latest order awaiting a receipt.
        candidates = [o for o in orders.values() if o["telegram_id"] == update.effective_user.id and o["status"] == "Chek kutilmoqda"]
        if not candidates:
            await update.message.reply_text("Avval buyurtma bering va to‘lov qiling. /start")
            return
        order = candidates[-1]
    else:
        order = orders.get(context.user_data["receipt_order_id"])
    if not order or order["telegram_id"] != update.effective_user.id or order["status"] != "Chek kutilmoqda":
        await update.message.reply_text("Chek uchun faol buyurtma topilmadi.")
        return
    order["status"] = "Chek admin tekshiruvida"
    caption = (f"🧾 CHEK — BUYURTMA #{order['id']}\\n"
               f"Telegram ID: {order['telegram_id']}\\nMinecraft nick: {order['minecraft_nick']}\\n"
               f"Mahsulot: {order['product_name']}\\nNarx: {order['price']}\\nHolat: Chek admin tekshiruvida")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash va berish", callback_data=f"approve:{order['id']}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{order['id']}")
    ]])
    try:
        if update.message.photo:
            await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=caption, reply_markup=kb)
        else:
            await context.bot.send_document(ADMIN_ID, update.message.document.file_id, caption=caption, reply_markup=kb)
        await update.message.reply_text(f"✅ Chek adminga yuborildi. Tasdiqni kuting. Buyurtma #{order['id']}.")
    except Exception:
        log.exception("Could not notify admin")
        order["status"] = "Chek yuborilmadi"
        await update.message.reply_text("Chekni adminga yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")

def run_rcon(command):
    with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT, timeout=8) as mcr:
        return mcr.command(command)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return
    try:
        result = await asyncio.to_thread(run_rcon, "list")
        await update.message.reply_text(f"🟢 Server RCON javobi:\\n{result[:1500]}")
    except Exception:
        await update.message.reply_text("🔴 Server bilan bog‘lanib bo‘lmadi. RCON host/port/password va server sozlamalarini tekshiring.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, on_receipt))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
