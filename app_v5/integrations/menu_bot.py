from __future__ import annotations
import asyncio, os, re, json, logging, tempfile
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

from app_v4_new.database.db import criar_tabela, upsert_usuario, upsert_nps
from .bridge import recommend_from_audio_file, recommend_from_youtube, list_db

logging.basicConfig(level=logging.INFO)

# Carrega variáveis de ambiente da raiz e de integrations/.env (prioridade)
load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
K_DEFAULT = int(os.getenv("BOT_K", "3"))
SR_DEFAULT = int(os.getenv("BOT_SR", "22050"))

REGISTER_NAME, REGISTER_EMAIL, MENU, GET_AUDIO, GET_YT, GET_LIST, GET_RATING = range(7)
YOUTUBE_RE = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/\S+", re.IGNORECASE)

def _menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📼 YouTube (1 vídeo)", callback_data="m_yt"),
         InlineKeyboardButton("🎙️ Áudio local", callback_data="m_audio")],
        [InlineKeyboardButton("🗂️ Listar banco", callback_data="m_list")],
        [InlineKeyboardButton("❌ Sair", callback_data="m_exit")],
    ])

def _fmt_items_md(items: list[dict]) -> str:
    if not items: return "Nenhuma recomendação encontrada."
    lines = ["🎯 *Recomendações:*", ""]
    for i, it in enumerate(items[:10], 1):
        t = it.get("titulo") or "Faixa"
        a = it.get("artista") or ""
        s = it.get("similaridade_fmt") or ""
        L = it.get("link") or ""
        head = f"*{i}. {t}*"
        if a: head += f" — _{a}_"
        tail = " | ".join([x for x in [s, L] if x])
        if tail: head += f"\n   {tail}"
        lines.append(head)
    return "\n".join(lines)

def _rating_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐",     callback_data="rate:1"),
         InlineKeyboardButton("⭐⭐",    callback_data="rate:2"),
         InlineKeyboardButton("⭐⭐⭐",   callback_data="rate:3"),
         InlineKeyboardButton("⭐⭐⭐⭐",  callback_data="rate:4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rate:5")]
    ])

# --------- Conversa ---------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_tabela()  # garante tb_musicas + tb_usuarios + tb_nps
    await update.message.reply_text(
        "👋 Olá! Bem-vindo(a) ao *FourierMatch*.\n\n"
        "Para começar, qual é o seu *nome completo*?",
        parse_mode="Markdown"
    )
    return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fullname = (update.message.text or "").strip()
    if len(fullname.split()) < 2:
        await update.message.reply_text("Por favor, informe o *nome completo* (nome e sobrenome).", parse_mode="Markdown")
        return REGISTER_NAME
    context.user_data["fullname"] = fullname
    await update.message.reply_text("Perfeito. Agora, informe seu *e-mail* (pessoal ou institucional).", parse_mode="Markdown")
    return REGISTER_EMAIL

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        await update.message.reply_text("E-mail inválido. Tente novamente.")
        return REGISTER_EMAIL
    context.user_data["email"] = email
    u = update.effective_user
    upsert_usuario(u.id, context.user_data["fullname"], email)  # MySQL
    await update.message.reply_text("Cadastro concluído ✅\n\nEscolha uma opção:", reply_markup=_menu_kb())
    return MENU

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "m_yt":
        await q.edit_message_text("Envie o *link do YouTube* (vídeo único).", parse_mode="Markdown"); return GET_YT
    if q.data == "m_audio":
        await q.edit_message_text("Envie um *áudio* (voice, .mp3, .wav...).", parse_mode="Markdown"); return GET_AUDIO
    if q.data == "m_list":
        rows = list_db(limit=20) or []
        if not rows:
            await q.edit_message_text("Banco vazio.", reply_markup=_menu_kb()); return MENU
        lines = ["🗂️ *Últimos itens:*", ""]
        for r in rows:
            lines.append(f"- #{r.get('id')}: *{r.get('titulo') or r.get('nome')}* — _{r.get('artista') or ''}_")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=_menu_kb()); return MENU
    if q.data == "m_exit":
        await q.edit_message_text("👋 Até mais!"); return ConversationHandler.END

async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not YOUTUBE_RE.search(text):
        await update.message.reply_text("Link inválido. Envie um URL do YouTube (youtube.com ou youtu.be)."); return GET_YT
    await update.message.reply_text("⏳ Processando link...")
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, recommend_from_youtube, text, K_DEFAULT, SR_DEFAULT)
    if r.get("status") != "ok":
        await update.message.reply_text(f"❌ Erro: {r.get('message') or 'falha'}", reply_markup=_menu_kb()); return MENU
    q = r.get("query") or {}
    musica_id = int(q.get("id") or 0)
    await update.message.reply_text(_fmt_items_md(r.get("items") or []), parse_mode="Markdown", disable_web_page_preview=True)
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "youtube", "input_ref": text, "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
    return GET_RATING

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.audio or update.message.voice or \
           (update.message.document if (update.message.document and (update.message.document.mime_type or "").startswith("audio/")) else None)
    if not file:
        await update.message.reply_text("Envie um *arquivo de áudio* (ou voice).", parse_mode="Markdown"); return GET_AUDIO
    tg_file = await file.get_file()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "input"
        wav = Path(td) / "input.wav"
        await tg_file.download_to_drive(custom_path=str(src))
        try:
            audio = AudioSegment.from_file(src)
            audio = audio.set_channels(1).set_frame_rate(SR_DEFAULT)
            audio.export(wav, format="wav")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao converter áudio: {e}", reply_markup=_menu_kb()); return MENU
        await update.message.reply_text("⏳ Extraindo e recomendando…")
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, recommend_from_audio_file, str(wav), K_DEFAULT, SR_DEFAULT)
    if r.get("status") != "ok":
        await update.message.reply_text(f"❌ Erro: {r.get('message') or 'falha'}", reply_markup=_menu_kb()); return MENU
    q = r.get("query") or {}
    musica_id = int(q.get("id") or 0)
    await update.message.reply_text(_fmt_items_md(r.get("items") or []), parse_mode="Markdown", disable_web_page_preview=True)
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "audio", "input_ref": "(arquivo enviado)", "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
    return GET_RATING

async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    try:
        _, rating_str = q.data.split(":", 1)
        rating = int(rating_str)
    except Exception:
        await q.edit_message_text("Avaliação inválida."); return MENU
    if not (1 <= rating <= 5):
        await q.edit_message_text("Avaliação inválida."); return MENU

    payload = context.user_data.get("last_rate_payload") or {}
    musica_id = int(payload.get("musica_id") or 0)
    if not musica_id:
        await q.edit_message_text("Contexto perdido. Faça uma nova consulta."); return MENU

    user = q.from_user
    try:
        upsert_nps(user_id=user.id, musica_id=musica_id, rating=rating,
                   channel=payload.get("channel"), input_ref=payload.get("input_ref"),
                   result_json=json.dumps(payload.get("result_json"), ensure_ascii=False))
        await q.edit_message_text(f"Obrigado pela avaliação: {rating} ⭐")
    except Exception as e:
        await q.edit_message_text(f"Erro ao salvar avaliação: {e}")

    await q.message.reply_text("Deseja fazer outra consulta?", reply_markup=_menu_kb()); return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado. Até mais! 👋"); return ConversationHandler.END

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN não definido (crie app_v4_new/integrations/.env ou exporte no ambiente)")
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_EMAIL:[MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
            MENU:          [CallbackQueryHandler(menu_cb, pattern=r"^m_")],
            GET_YT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube)],
            GET_AUDIO:     [MessageHandler((filters.AUDIO | filters.VOICE | filters.Document.AUDIO), handle_audio)],
            GET_RATING:    [CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:[1-5]$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
