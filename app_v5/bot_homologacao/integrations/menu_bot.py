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

from app_v5.database.db import (
    criar_tabela, upsert_usuario, upsert_nps, update_nps_algoritmo, get_usuario
)
from .bridge import recommend_from_audio_file, recommend_from_youtube, list_db
from .shazam_flow import recognize_and_pick_youtube

logging.basicConfig(level=logging.INFO)

# Carrega variáveis de ambiente da raiz e de integrations/.env (prioridade)
load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
K_DEFAULT = int(os.getenv("BOT_K", "3"))
SR_DEFAULT = int(os.getenv("BOT_SR", "22050"))

(
    REGISTER_NAME, REGISTER_EMAIL, REGISTER_STREAM,
    MENU, GET_AUDIO, GET_YT, GET_LIST,
    GET_RATING, GET_ALG, GET_SNIPPET
) = range(10)

YOUTUBE_RE = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/\S+", re.IGNORECASE)

STREAMING_CHOICES = [
    ("spotify",    "Spotify"),
    ("ytmusic",    "YouTube Music"),
    ("deezer",     "Deezer"),
    ("apple",      "Apple Music"),
    ("tidal",      "Tidal"),
    ("soundcloud", "SoundCloud"),
    ("other",      "Outra")
]

def _menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📼 YouTube (1 vídeo)", callback_data="m_yt"),
         InlineKeyboardButton("🎙️ Áudio local", callback_data="m_audio")],
        [InlineKeyboardButton("🎤 Trecho (Shazam até 30s)", callback_data="m_snip")],
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

def _stream_kb():
    rows = []
    row = []
    for code, label in STREAMING_CHOICES:
        row.append(InlineKeyboardButton(label, callback_data=f"s_{code}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def _alg_vote_kb(pref_code: str | None):
    label_map = {c:l for c,l in STREAMING_CHOICES}
    pref_label = label_map.get(pref_code or "", "Sua plataforma")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎧 {pref_label}", callback_data=f"alg:{pref_code or 'preferida'}"),
         InlineKeyboardButton("🧠 FourierMatch",  callback_data="alg:sistema")],
        [InlineKeyboardButton("🔁 Outra plataforma", callback_data="alg:other")]
    ])

# --------- Conversa ---------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_tabela()  # garante tabelas/colunas
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
    await update.message.reply_text(
        "Qual plataforma de *streaming de música* você mais usa?",
        parse_mode="Markdown",
        reply_markup=_stream_kb()
    )
    return REGISTER_STREAM

async def register_stream_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    m = re.match(r"^s_(.+)$", q.data or "")
    if not m:
        await q.edit_message_text("Opção inválida."); return REGISTER_STREAM
    pref = m.group(1)
    context.user_data["streaming_pref"] = pref
    user = q.from_user
    upsert_usuario(user.id, context.user_data.get("fullname",""), context.user_data.get("email",""), streaming_pref=pref)
    await q.edit_message_text("Cadastro concluído ✅")
    await q.message.reply_text("Escolha uma opção:", reply_markup=_menu_kb())
    return MENU

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "m_yt":
        await q.edit_message_text("Envie o *link do YouTube* (vídeo único).", parse_mode="Markdown"); return GET_YT
    if q.data == "m_audio":
        await q.edit_message_text("Envie um *áudio* (voice, .mp3, .wav...).", parse_mode="Markdown"); return GET_AUDIO
    if q.data == "m_snip":
        await q.edit_message_text("Grave e envie um *trecho de até 30s* (voice do Telegram é ideal).", parse_mode="Markdown"); return GET_SNIPPET
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

def _rating_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐",     callback_data="rate:1"),
         InlineKeyboardButton("⭐⭐",    callback_data="rate:2"),
         InlineKeyboardButton("⭐⭐⭐",   callback_data="rate:3"),
         InlineKeyboardButton("⭐⭐⭐⭐",  callback_data="rate:4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rate:5")]
    ])

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

async def handle_snippet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # aceita voice ou audio, mas exige duração <= 30s
    msg = update.message
    file = msg.voice or msg.audio or \
           (msg.document if (msg.document and (msg.document.mime_type or "").startswith("audio/")) else None)
    if not file:
        await msg.reply_text("Envie um *voice* do Telegram ou outro áudio (até 30s).", parse_mode="Markdown"); return GET_SNIPPET

    # verifica duração quando disponível
    dur = getattr(file, "duration", None)
    if dur and int(dur) > 31:
        await msg.reply_text("⚠️ O trecho tem mais de 30 segundos. Por favor, reenvie um *trecho de até 30s*.", parse_mode="Markdown")
        return GET_SNIPPET

    tg_file = await file.get_file()
    await msg.reply_text("🔎 Reconhecendo com Shazam…")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "snippet"
        wav = Path(td) / "snippet.wav"
        await tg_file.download_to_drive(custom_path=str(src))
        try:
            audio = AudioSegment.from_file(src)
            # limita a 30s mesmo se maior (corta)
            audio = audio.set_channels(1).set_frame_rate(44100)
            if len(audio) > 30000:
                audio = audio[:30000]
            audio.export(wav, format="wav")
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao converter áudio: {e}", parse_mode="Markdown")
            return MENU

        # Shazam (async) → alvo no YouTube (url ou ytsearch1)
        shz = await recognize_and_pick_youtube(str(wav))

    if not shz.get("ok"):
        await msg.reply_text(f"😕 Não reconheci o trecho. {shz.get('error','Tente outro pedaço com menos ruído.')}")
        return MENU

    title = shz.get("title") or ""
    artist = shz.get("artist") or ""
    target = shz.get("target") or ""
    source = shz.get("from") or "search"
    header = f"🎵 Reconhecido: *{title}* — _{artist}_"
    if source == "direct":
        header += "\n🔗 Encontrei link direto no YouTube."
    else:
        header += "\n🔎 Buscando no YouTube pelo melhor resultado…"
    await msg.reply_text(header, parse_mode="Markdown", disable_web_page_preview=True)

    # Usa o mesmo pipeline do YouTube para baixar + ingerir + recomendar
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, recommend_from_youtube, target, K_DEFAULT, SR_DEFAULT)
    if r.get("status") != "ok":
        await msg.reply_text(f"❌ Erro ao baixar/ingestir do YouTube: {r.get('message') or 'falha'}", reply_markup=_menu_kb())
        return MENU

    q = r.get("query") or {}
    musica_id = int(q.get("id") or 0)
    await msg.reply_text(_fmt_items_md(r.get("items") or []), parse_mode="Markdown", disable_web_page_preview=True)

    # guarda para a avaliação
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "snippet", "input_ref": f"shazam:{title} - {artist}", "result_json": r
    }
    await msg.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
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
    except Exception as e:
        await q.edit_message_text(f"Erro ao salvar avaliação: {e}")
        return MENU

    # Após a nota, pedir voto de algoritmo
    pref = context.user_data.get("streaming_pref")
    if not pref:
        u = get_usuario(user.id) or {}
        pref = u.get("streaming_pref")
    await q.edit_message_text("✅ Avaliação registrada.")
    await q.message.reply_text(
        "Agora, *qual algoritmo te entregou a melhor recomendação*?",
        reply_markup=_alg_vote_kb(pref),
        parse_mode="Markdown"
    )
    return GET_ALG

async def handle_algvote_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    try:
        _, value = (q.data or "").split(":", 1)
    except Exception:
        await q.edit_message_text("Opção inválida."); return MENU
    payload = context.user_data.get("last_rate_payload") or {}
    musica_id = int(payload.get("musica_id") or 0)
    if not musica_id:
        await q.edit_message_text("Contexto perdido. Faça uma nova consulta."); return MENU

    user = q.from_user
    try:
        update_nps_algoritmo(user_id=user.id, musica_id=musica_id, alg_vencedor=value)
        await q.edit_message_text("🗳️ Obrigado pelo voto!")
    except Exception as e:
        await q.edit_message_text(f"Erro ao registrar voto: {e}")
    await q.message.reply_text("Deseja fazer outra consulta?", reply_markup=_menu_kb())
    return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado. Até mais! 👋"); return ConversationHandler.END

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN não definido (crie app_v5/integrations/.env ou exporte no ambiente)")
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REGISTER_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
            REGISTER_STREAM: [CallbackQueryHandler(register_stream_cb, pattern=r"^s_")],
            MENU:            [CallbackQueryHandler(menu_cb, pattern=r"^m_")],
            GET_YT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube)],
            GET_AUDIO:       [MessageHandler((filters.AUDIO | filters.VOICE | filters.Document.AUDIO), handle_audio)],
            GET_SNIPPET:     [MessageHandler((filters.VOICE | filters.AUDIO | filters.Document.AUDIO), handle_snippet)],
            GET_RATING:      [CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:[1-5]$")],
            GET_ALG:         [CallbackQueryHandler(handle_algvote_cb, pattern=r"^alg:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
