import asyncio, logging, tempfile, os, ssl, json, secrets, string
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web
ssl._create_default_https_context = ssl._create_unverified_context
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Используем GROQ - бесплатно! Если нет GROQ ключа, пробуем OpenAI
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
ADMIN_IDS = [2113910988]
TRIAL_COUNT = 1

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
# Groq - бесплатный Whisper API, совместим с OpenAI
client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "database"
DB_DIR.mkdir(exist_ok=True)
USERS_FILE = DB_DIR / "users_sub.json"
CODES_FILE = DB_DIR / "codes_sub.json"

print(f"🤖 FREE GROQ VERSION - Token: {BOT_TOKEN[:6] if BOT_TOKEN else 'NO'}... Groq: {'YES' if GROQ_API_KEY else 'NO'}")

def load_json(path, default):
    if not path.exists(): return default
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return default
def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
def load_users(): return load_json(USERS_FILE, {})
def load_codes(): return load_json(CODES_FILE, {})
def is_subscribed(user_id: int):
    users = load_users()
    u = users.get(str(user_id))
    if not u: return False, 0, "no_user"
    expiry_str = u.get("expiry")
    if not expiry_str: return False, 0, "no_expiry"
    try: expiry = datetime.fromisoformat(expiry_str)
    except: return False, 0, "bad_date"
    now = datetime.now()
    if now > expiry: return False, 0, "expired"
    days_left = (expiry - now).days + 1
    return True, days_left, u.get("plan","unknown")
def add_subscription(user_id: int, days: int, plan_name: str):
    users = load_users()
    now = datetime.now()
    uid = str(user_id)
    existing = users.get(uid)
    if existing and existing.get("expiry"):
        try:
            existing_expiry = datetime.fromisoformat(existing["expiry"])
            if existing_expiry > now: now = existing_expiry
        except: pass
    new_expiry = now + timedelta(days=days)
    users[uid] = {"expiry": new_expiry.isoformat(), "plan": plan_name, "updated_at": datetime.now().isoformat(), "trial_used": existing.get("trial_used",0) if existing else 0}
    save_json(USERS_FILE, users)
    return new_expiry
def generate_code(days: int, plan_name: str):
    codes = load_codes()
    rand = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    code = f"{plan_name.upper()}-{rand}-{days}D"
    codes[code] = {"days": days, "plan": plan_name, "used": False, "used_by": None, "created_at": datetime.now().isoformat()}
    save_json(CODES_FILE, codes)
    return code
def get_kb(is_sub, days_left=0):
    if is_sub:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🎤 How to record")],[KeyboardButton(text="📅 My subscription"), KeyboardButton(text="ℹ️ Help")]], resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔑 Activate code")],[KeyboardButton(text="💳 Buy subscription"), KeyboardButton(text="ℹ️ Help")]], resize_keyboard=True)
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/gen 30"), KeyboardButton(text="/gen 90"), KeyboardButton(text="/gen 180")],[KeyboardButton(text="/codes"), KeyboardButton(text="/users")],[KeyboardButton(text="🎤 How to record")]], resize_keyboard=True)

async def transcribe_voice(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            # Groq бесплатный whisper-large-v3 - самый точный для IELTS
            tr = await client.audio.transcriptions.create(
                model="whisper-large-v3", 
                file=f, 
                language="en",
                response_format="text"
            )
            # Groq возвращает текст напрямую если response_format=text
            if isinstance(tr, str):
                return tr.strip()
            return tr.text.strip() if hasattr(tr, 'text') else str(tr).strip()
    except Exception as e:
        print(f"Groq STT error: {e}")
        return f"❌ Error: {e}"

@dp.message(Command("start"))
async def cmd_start(m: Message):
    ok, days_left, info = is_subscribed(m.from_user.id)
    users = load_users()
    uid = str(m.from_user.id)
    if uid not in users:
        users[uid] = {"expiry": None, "plan": "trial", "trial_used": 0, "created_at": datetime.now().isoformat()}
        save_json(USERS_FILE, users)
    if ok:
        await m.answer(f"👋 Welcome back!\n\n✅ Subscription active: **{info}**\n📅 Days left: **{days_left}**\n\nJust send voice message to transcribe.", reply_markup=get_kb(True, days_left))
    else:
        trial_used = users.get(uid, {}).get("trial_used",0)
        trial_msg = f"\n🎁 You have {TRIAL_COUNT - trial_used} free transcription(s)!" if trial_used < TRIAL_COUNT else ""
        await m.answer(f"👋 **IELTS Transcriber Bot**\n\n❌ No active subscription.{trial_msg}\n\n💳 **Plans:**\n• 1 Month — 10€\n• 3 Months — 25€\n• 6 Months — 40€\n\nTo activate, press 🔑 Activate code", reply_markup=get_kb(False))
@dp.message(F.text == "📅 My subscription")
async def my_sub(m: Message):
    ok, days_left, plan = is_subscribed(m.from_user.id)
    if ok: await m.answer(f"✅ Plan: {plan}\n📅 Days left: {days_left}", reply_markup=get_kb(True))
    else: await m.answer("❌ No active subscription. Press 💳 Buy subscription", reply_markup=get_kb(False))
@dp.message(F.text == "💳 Buy subscription")
async def buy(m: Message):
    await m.answer("💳 **How to buy:**\n\n1️⃣ 1 Month — 10€\n2️⃣ 3 Months — 25€\n3️⃣ 6 Months — 40€\n\nAfter payment you will receive activation code\nThen press 🔑 Activate code\n\nContact: @Gmayer_1", reply_markup=get_kb(False))
@dp.message(F.text == "🔑 Activate code")
async def ask_code(m: Message):
    await m.answer("🔑 Send me your activation code.\nExample: `MONTH-AB12-30D`\nYou can also type /activate YOURCODE")
@dp.message(Command("activate"))
async def activate_cmd(m: Message):
    args = m.text.split()
    if len(args) < 2:
        await m.answer("Usage: /activate YOURCODE")
        return
    code = args[1].strip().upper()
    await redeem_code(m, code)
@dp.message(F.text.regexp(r"^(MONTH|3MONTH|6MONTH|\d+D)-[A-Z0-9]{4}-\d+D$"))
async def auto_redeem(m: Message):
    code = m.text.strip().upper()
    await redeem_code(m, code)
async def redeem_code(m: Message, code: str):
    codes = load_codes()
    c = codes.get(code)
    if not c:
        await m.answer("❌ Code not found.", reply_markup=get_kb(False))
        return
    if c.get("used"):
        await m.answer(f"❌ Code already used by {c.get('used_by')}", reply_markup=get_kb(False))
        return
    days = c.get("days", 30)
    plan = c.get("plan", f"{days}D")
    expiry = add_subscription(m.from_user.id, days, plan)
    c["used"] = True
    c["used_by"] = str(m.from_user.id)
    c["used_at"] = datetime.now().isoformat()
    save_json(CODES_FILE, codes)
    await m.answer(f"✅ **Activated!**\n\nPlan: {plan}\nDays: {days}\nValid until: {expiry.strftime('%d.%m.%Y')}", reply_markup=get_kb(True, days))
@dp.message(F.text == "🎤 How to record")
async def how(m: Message):
    ok, _, _ = is_subscribed(m.from_user.id)
    await m.answer("🎤 Hold the 🎙️ mic icon → speak → release → I transcribe", reply_markup=get_kb(ok))
@dp.message(F.text == "ℹ️ Help")
async def help_msg(m: Message):
    ok, _, _ = is_subscribed(m.from_user.id)
    await m.answer("Send voice message → get transcript.", reply_markup=get_kb(ok))
@dp.message(Command("gen"))
async def gen_cmd(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        await m.answer("⛔ Admin only")
        return
    args = m.text.split()
    if len(args) < 2:
        await m.answer("Usage: /gen 30")
        return
    try: days = int(args[1])
    except:
        await m.answer("Days must be number")
        return
    plan = "MONTH" if days==30 else "3MONTH" if days==90 else "6MONTH" if days==180 else f"{days}D"
    code = generate_code(days, plan)
    await m.answer(f"✅ Code generated:\n`{code}`\nPlan: {plan}, Days: {days}", reply_markup=get_admin_kb())
@dp.message(Command("codes"))
async def list_codes(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    codes = load_codes()
    if not codes:
        await m.answer("No codes")
        return
    txt = "📋 Codes:\n"
    for code, data in list(codes.items())[-20:]:
        status = "✅ used" if data.get("used") else "🟢 free"
        txt += f"{code} - {data.get('days')}d - {status}\n"
    await m.answer(txt)
@dp.message(Command("users"))
async def list_users(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    users = load_users()
    txt = f"👥 Users: {len(users)}\n"
    for uid, data in list(users.items())[-20:]:
        exp = data.get("expiry","none")
        txt += f"{uid} - {data.get('plan')} - {exp}\n"
    await m.answer(txt)
@dp.message(F.voice | F.audio | F.video_note)
async def handle_voice(m: Message):
    user_id = m.from_user.id
    ok, days_left, plan = is_subscribed(user_id)
    users = load_users()
    uid = str(user_id)
    u = users.get(uid, {})
    trial_used = u.get("trial_used", 0)
    if not ok:
        if trial_used < TRIAL_COUNT:
            users[uid]["trial_used"] = trial_used + 1
            save_json(USERS_FILE, users)
            await m.answer(f"🎁 Free trial {trial_used+1}/{TRIAL_COUNT} used.")
        else:
            await m.answer("🔒 Subscription required!\nPress 💳 Buy subscription", reply_markup=get_kb(False))
            return
    file_id = m.voice.file_id if m.voice else m.audio.file_id if m.audio else m.video_note.file_id
    file = await bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tf:
        tmp_path = tf.name
    await bot.download_file(file.file_path, tmp_path)
    await m.answer("🎧 Transcribing (FREE Groq)...")
    transcript = await transcribe_voice(tmp_path)
    try: os.remove(tmp_path)
    except: pass
    if not transcript:
        await m.answer("❌ Could not transcribe.", reply_markup=get_kb(ok))
        return
    await m.answer(f"📝 **Transcript:**\n\n{transcript}", reply_markup=get_kb(ok))
@dp.message()
async def any_text(m: Message):
    if m.text.startswith("/"): return
    ok, _, _ = is_subscribed(m.from_user.id)
    await m.answer("🎙️ Send voice message. Use 🔑 Activate code if you have code.", reply_markup=get_kb(ok))

async def handle_health(request):
    return web.Response(text="Bot is alive! FREE Groq ✅")
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web server started on port {port}")
async def main():
    await start_web_server()
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())
