# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import re
import json
import logging
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TimedOut, RetryAfter, NetworkError
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

from app_v5.database.db import (
    criar_tabela, upsert_usuario, upsert_nps, update_nps_algoritmo, get_usuario
)
from .bridge import (
    recommend_from_audio_file, recommend_from_youtube, list_db,
    process_playlist_youtube, recalibrate
)
from .shazam_flow import recognize_and_pick_youtube

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Carrega variáveis de ambiente padrão (ex.: BOT_TOKEN) do .env ao lado deste arquivo
load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))

# ---------- Estados ----------
REGISTER_NAME, REGISTER_EMAIL, REGISTER_STREAM, MENU, GET_YT, GET_AUDIO, GET_SNIPPET, GET_PLAYLIST, GET_RATING, GET_ALG = range(10)

K_DEFAULT = int(os.getenv("BOT_K", "3"))
SR_DEFAULT = int(os.getenv("BOT_SR", "22050"))

STREAM_CHOICES = [
    ("spotify",    "Spotify"),
    ("youtube",    "YouTube Music"),
    ("applemusic", "Apple Music"),
    ("deezer",     "Deezer"),
    ("other",      "Outra")
]

CLI_MENU_TEXT = (
    "🎧  === Menu Principal ===\n"
    "1) Processar áudio local\n"
    "2) Processar link do YouTube\n"
    "3) Upload em massa (pasta local)\n"
    "4) Recalibrar & Recomendar\n"
    "5) Playlist do YouTube (bulk)\n"
    "6) Listar últimos itens do banco\n"
    "7) Reconhecer trecho de áudio (Shazam)\n"
    "0) Sair"
)

def _stream_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl, callback_data=f"s_{key}")] for key, lbl in STREAM_CHOICES
    ])

def _menu_kb():
    # Espelha CLI com botões numéricos equivalentes + opção extra (7) Shazam
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1) Áudio local", callback_data="m_1"),
         InlineKeyboardButton("2) Link YouTube", callback_data="m_2")],
        [InlineKeyboardButton("3) Upload em massa (CLI)", callback_data="m_3")],
        [InlineKeyboardButton("4) Recalibrar & Recomendar", callback_data="m_4")],
        [InlineKeyboardButton("5) Playlist YouTube (bulk)", callback_data="m_5")],
        [InlineKeyboardButton("6) Listar últimos", callback_data="m_6")],
        [InlineKeyboardButton("7) Trecho (Shazam)", callback_data="m_7")],
        [InlineKeyboardButton("0) Sair", callback_data="m_0")],
    ])

# ---------- Formatadores (TEXTO PURO) ----------
def _fmt_items_text(items: list[dict]) -> str:
    """Renderiza lista de recomendações em texto puro (sem HTML/Markdown)."""
    if not items:
        return "Nenhuma recomendação encontrada."
    lines = ["🎯 Recomendações:", ""]
    for i, it in enumerate(items, 1):
        sim = it.get("similaridade_fmt") or ""
        link = it.get("link") or ""
        titulo = (it.get("titulo") or "").replace("\n", " ").strip()
        artista = (it.get("artista") or "").replace("\n", " ").strip()
        line = f"{i}. {titulo} — {artista} · {sim}"
        if link:
            line += f"\n   {link}"
        lines.append(line)
    return "\n".join(lines)

def _fmt_table_rows_text(rows: list[dict]) -> str:
    """Listagem simples em texto: cabeçalho e linhas com separador |."""
    cols = ["id", "titulo", "artista", "caminho", "created_at"]
    header = " | ".join(cols)
    sep = "-" * len(header)
    out = [header, sep]
    for r in rows:
        idv = r.get("id")
        titulo = r.get("titulo") or r.get("nome", "") or ""
        artista = r.get("artista", "") or ""
        caminho = r.get("caminho", "") or ""
        created = r.get("created_at", "") or ""
        out.append(f"{idv} | {titulo} | {artista} | {caminho} | {created}")
    return "\n".join(out)

def _rating_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1", callback_data="rate:1"),
         InlineKeyboardButton("⭐ 2", callback_data="rate:2"),
         InlineKeyboardButton("⭐ 3", callback_data="rate:3"),
         InlineKeyboardButton("⭐ 4", callback_data="rate:4"),
         InlineKeyboardButton("⭐ 5", callback_data="rate:5")]
    ])

def _algvote_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Esta plataforma", callback_data="alg:A"),
         InlineKeyboardButton("Outro streaming", callback_data="alg:B"),
         InlineKeyboardButton("Empate", callback_data="alg:=")]
    ])

# ---------- Preferência de identificador do usuário ----------
def _user_ref(context: ContextTypes.DEFAULT_TYPE):
    """Retorna o identificador preferencial do usuário para o DB (id AI; fallback: email)."""
    return context.user_data.get("user_pk") or context.user_data.get("email")

# ---------- Util: edição resiliente ----------
async def safe_edit(q, text: str, **kwargs):
    """
    Tenta editar a mensagem do callback. Em caso de TimedOut/NetworkError,
    faz fallback para enviar uma nova mensagem no chat.
    """
    try:
        return await q.edit_message_text(text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 2))
        try:
            return await q.edit_message_text(text, **kwargs)
        except Exception:
            pass
    except (TimedOut, NetworkError):
        pass
    # fallback
    allowed = {k: v for k, v in kwargs.items() if k in {"reply_markup", "disable_web_page_preview"}}
    return await q.message.reply_text(text, **allowed)

# ---------- Fluxo de cadastro ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_tabela()  # garante tb_usuarios / tb_nps etc.
    await update.message.reply_text(
        "🎵 Bem-vindo ao FourierMatch!.\n\n"
        "Aqui você encontra músicas parecidas de verdade!.\n"
        "Nosso sistema entende a melodia e as frequências do som para recomendar faixas que combinam com o que você curte — muito além do “quem ouviu isso \ttambém ouviu aquilo.\n\n"
        "👇🏼Para começar, qual é o seu nome completo?👇🏼"
    )
    return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fullname = (update.message.text or "").strip()
    if len(fullname.split()) < 2:
        await update.message.reply_text("Por favor, informe o nome completo (nome e sobrenome).")
        return REGISTER_NAME
    context.user_data["fullname"] = fullname
    await update.message.reply_text("Perfeito. Agora, informe seu e-mail (pessoal ou institucional).")
    return REGISTER_EMAIL

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        await update.message.reply_text("E-mail inválido. Tente novamente.")
        return REGISTER_EMAIL
    context.user_data["email"] = email
    await update.message.reply_text(
        "Qual plataforma de streaming de música você mais usa?",
        reply_markup=_stream_kb()
    )
    return REGISTER_STREAM

async def register_stream_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Registrando…", show_alert=False)
    m = re.match(r"^s_(.+)$", q.data or "")
    pref = (m.group(1) if m else "other")
    user = update.effective_user
    fullname = context.user_data.get("fullname", "")
    email = context.user_data.get("email", "")

    # Feedback imediato para evitar timeout
    await safe_edit(q, "Processando cadastro…")

    # Upsert no DB em executor (não bloqueia o bot) — capturando o PK AI
    loop = asyncio.get_running_loop()
    try:
        pk = await loop.run_in_executor(None, upsert_usuario, None, fullname, email, pref)
        context.user_data["user_pk"] = int(pk)  # ✅ guarda o id autoincrementado para uso futuro
    except Exception as e:
        await q.message.reply_text(f"⚠️ Erro ao salvar cadastro: {e}")
        await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
        return MENU

    await safe_edit(q, "Cadastro concluído ✅")
    await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

# ---------- Menu (callbacks e texto numérico) ----------
async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "m_1":
        await safe_edit(q, "Envie um áudio (voice, .mp3, .wav...)."); return GET_AUDIO
    if data == "m_2":
        await safe_edit(q, "Envie o link do YouTube (vídeo único)."); return GET_YT
    if data == "m_3":
        await safe_edit(q, "Opção 3 (Upload em massa) é exclusiva da CLI.", reply_markup=_menu_kb()); return MENU
    if data == "m_4":
        await safe_edit(q, "🛠️ Recalibrando (ajustando scaler)…")
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, recalibrate)
        if r.get("status") == "ok":
            await q.message.reply_text(
                f"✅ Base calibrada: {r['itens']} faixas × {r['dim']} dims.\n"
                f"Agora envie um áudio local (opção 1) para recomendar."
            )
        else:
            await q.message.reply_text(f"❌ Erro ao recalibrar: {r.get('message')}")
        await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb()); return MENU
    if data == "m_5":
        await safe_edit(q, "Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    if data == "m_6":
        rows = list_db(limit=20) or []
        if not rows:
            await safe_edit(q, "Banco vazio.", reply_markup=_menu_kb()); return MENU
        await safe_edit(q, _fmt_table_rows_text(rows), reply_markup=_menu_kb()); return MENU
    if data == "m_7":
        await safe_edit(q, "Envie um trecho de áudio (até 30s)."); return GET_SNIPPET
    if data == "m_0":
        await safe_edit(q, "Sessão encerrada. 👋"); return ConversationHandler.END
    await safe_edit(q, CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "1":
        await update.message.reply_text("Envie um áudio (voice, .mp3, .wav...)."); return GET_AUDIO
    if text == "2":
        await update.message.reply_text("Envie o link do YouTube (vídeo único)."); return GET_YT
    if text == "3":
        await update.message.reply_text("Opção 3 (Upload em massa) é exclusiva da CLI.", reply_markup=_menu_kb()); return MENU
    if text == "4":
        await update.message.reply_text("🛠️ Recalibrando (ajustando scaler)…")
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, recalibrate)
        if r.get("status") == "ok":
            await update.message.reply_text(
                f"✅ Base calibrada: {r['itens']} faixas × {r['dim']} dims.\n"
                f"Agora envie um áudio local (opção 1) para recomendar."
            )
        else:
            await update.message.reply_text(f"❌ Erro ao recalibrar: {r.get('message')}")
        await update.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb()); return MENU
    if text == "5":
        await update.message.reply_text("Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    if text == "6":
        rows = list_db(limit=20) or []
        if not rows:
            await update.message.reply_text("Banco vazio.", reply_markup=_menu_kb()); return MENU
        await update.message.reply_text(_fmt_table_rows_text(rows), reply_markup=_menu_kb()); return MENU
    if text == "7":
        await update.message.reply_text("Envie um trecho de áudio (até 30s)."); return GET_SNIPPET
    if text == "0" or text.lower() in {"sair","exit","quit"}:
        await update.message.reply_text("Sessão encerrada. 👋"); return ConversationHandler.END
    await update.message.reply_text("Envie uma opção válida do menu (0..7) ou use os botões abaixo.", reply_markup=_menu_kb())
    return MENU

# ---------- Handlers de ações ----------
async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Envie um link do YouTube."); return GET_YT
    await update.message.reply_text("⏳ Baixando e recomendando…")
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, recommend_from_youtube, text, K_DEFAULT, SR_DEFAULT)
    if r.get("status") != "ok":
        await update.message.reply_text(f"❌ Erro: {r.get('message') or 'falha'}", reply_markup=_menu_kb()); return MENU
    q = r.get("query") or {}
    musica_id = int(q.get("id") or 0)
    await update.message.reply_text(_fmt_items_text(r.get("items") or []), disable_web_page_preview=True)
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "youtube", "input_ref": text, "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
    return GET_RATING

async def handle_playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    await update.message.reply_text("⏳ Baixando itens da playlist e processando…")
    loop = asyncio.get_running_loop()
    sr = SR_DEFAULT
    try:
        r = await loop.run_in_executor(None, process_playlist_youtube, text, sr)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar playlist: {e}", reply_markup=_menu_kb())
        return MENU
    if isinstance(r, dict) and r.get("status") == "ok":
        await update.message.reply_text(f"✅ Processados {r.get('processados',0)}/{r.get('total',0)} itens.", reply_markup=_menu_kb())
    else:
        msg = (r or {}).get("message") if isinstance(r, dict) else None
        await update.message.reply_text(f"❌ Erro: {msg or 'falha ao processar playlist.'}", reply_markup=_menu_kb())
    return MENU

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.audio or update.message.voice or \
           (update.message.document if (update.message.document and (update.message.document.mime_type or '').startswith('audio/')) else None)
    if not file:
        await update.message.reply_text("Envie um arquivo de áudio (ou voice)."); return GET_AUDIO
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
    await update.message.reply_text(_fmt_items_text(r.get("items") or []), disable_web_page_preview=True)
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "audio_local", "input_ref": q.get("caminho",""), "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
    return GET_RATING

async def handle_snippet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file = msg.voice or msg.audio or (msg.document if (msg.document and (msg.document.mime_type or '').startswith('audio/')) else None)
    if not file:
        await msg.reply_text("Envie um trecho de áudio (até ~30s)."); return GET_SNIPPET
    dur = getattr(file, "duration", None)
    if dur and int(dur) > 31:
        await msg.reply_text("⚠️ O trecho tem mais de 30 segundos; por favor, reenvie um trecho de até 30s.")
        return GET_SNIPPET

    tg_file = await file.get_file()
    await msg.reply_text("🔎 Reconhecendo com Shazam…")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "snippet"
        wav = Path(td) / "snippet.wav"
        await tg_file.download_to_drive(custom_path=str(src))
        try:
            audio = AudioSegment.from_file(src)
            audio = audio.set_channels(1).set_frame_rate(44100)
            if len(audio) > 30_000:
                audio = audio[:30_000]
            audio.export(wav, format="wav")
        except Exception as e:
            await msg.reply_text(f"❌ Erro ao preparar trecho: {e}", reply_markup=_menu_kb()); return MENU

        try:
            r = await recognize_and_pick_youtube(str(wav))
        except Exception as e:
            await msg.reply_text(f"❌ Reconhecimento falhou: {e}", reply_markup=_menu_kb()); return MENU

    if not r.get("ok"):
        await msg.reply_text(f"❌ Não reconhecido: {r.get('error') or 'sem correspondência.'}", reply_markup=_menu_kb()); return MENU

    title = (r.get("title","") or "").replace("\n", " ")
    artist = (r.get("artist","") or "").replace("\n", " ")
    await msg.reply_text(f"🎯 Reconhecido: {title} — {artist}\n➡️ Enviando para recomendação…")

    target = r.get("target")
    if target:
        loop = asyncio.get_running_loop()
        rec = await loop.run_in_executor(None, recommend_from_youtube, target, K_DEFAULT, SR_DEFAULT)
        if rec.get("status") == "ok":
            q = rec.get("query") or {}
            musica_id = int(q.get("id") or 0)
            await msg.reply_text(_fmt_items_text(rec.get("items") or []), disable_web_page_preview=True)
            context.user_data["last_rate_payload"] = {
                "musica_id": musica_id, "channel": "snippet", "input_ref": target, "result_json": rec
            }
            await msg.reply_text("Como você avalia esse resultado?", reply_markup=_rating_kb())
            return GET_RATING
        else:
            await msg.reply_text(f"❌ Erro ao recomendar: {rec.get('message')}", reply_markup=_menu_kb()); return MENU
    else:
        await msg.reply_text("❌ Não foi possível construir destino do YouTube.", reply_markup=_menu_kb()); return MENU

# ---------- Pós-ação: coleta de NPS e voto de algoritmo ----------
async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^rate:(\d)$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida.", reply_markup=_menu_kb()); return MENU
    rating = int(m.group(1))
    payload = context.user_data.get("last_rate_payload") or {}

    # Usa o id autoincrementado (ou email como fallback)
    user_ref = _user_ref(context)
    if not user_ref:
        await safe_edit(q, "Não encontrei seu cadastro nesta sessão. Envie /start para cadastrar e poder avaliar.",
                        reply_markup=_menu_kb())
        return MENU

    try:
        upsert_nps(
            user_ref, int(payload.get("musica_id") or 0), rating,
            channel=payload.get("channel"), input_ref=payload.get("input_ref"),
            result_json=json.dumps(payload.get("result_json") or {})
        )
        await safe_edit(q, "✅ Obrigado pela avaliação!")
    except Exception as e:
        await safe_edit(q, f"⚠️ Erro ao salvar avaliação: {e}")

    await q.message.reply_text("Se fosse escolher, qual plataforma te agradou mais?", reply_markup=_algvote_kb())
    return GET_ALG

async def handle_algvote_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^alg:(.+)$", q.data or "")
    choice = (m.group(1) if m else "=")
    payload = context.user_data.get("last_rate_payload") or {}

    # Usa o id autoincrementado (ou email como fallback)
    user_ref = _user_ref(context)
    if not user_ref:
        await safe_edit(q, "Não encontrei seu cadastro nesta sessão. Envie /start para cadastrar e poder votar.",
                        reply_markup=_menu_kb())
        return MENU

    try:
        update_nps_algoritmo(user_ref, int(payload.get("musica_id") or 0), choice)
        await safe_edit(q, "👍 Voto registrado.")
    except Exception as e:
        await safe_edit(q, f"⚠️ Erro ao registrar: {e}")
    await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sessão cancelada. 👋")
    return ConversationHandler.END

# ---------- Error handler global ----------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        import traceback
        tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
        log.error("Unhandled error: %s\n%s", context.error, tb)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Ocorreu um erro temporário. Tente novamente.")
    except Exception:
        pass

def main():
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina BOT_TOKEN no ambiente ou em app_v5/integrations/.env")

    # Aumenta timeouts de rede para evitar ReadTimeout em conexões lentas
    request = HTTPXRequest(
        connect_timeout=float(os.getenv("TG_CONNECT_TIMEOUT", 20)),
        read_timeout=float(os.getenv("TG_READ_TIMEOUT", 60)),
        write_timeout=float(os.getenv("TG_WRITE_TIMEOUT", 60)),
        pool_timeout=float(os.getenv("TG_POOL_TIMEOUT", 10)),
    )

    app = Application.builder().token(token).request(request).build()

    # Filtro para Document de áudio (compat v20/v21)
    try:
        DOC_AUDIO_FILTER = filters.Document.AUDIO
    except Exception:
        DOC_AUDIO_FILTER = filters.Document.MimeType("audio/")

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REGISTER_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
            REGISTER_STREAM: [CallbackQueryHandler(register_stream_cb, pattern=r"^s_")],

            MENU: [
                CallbackQueryHandler(menu_cb, pattern=r"^m_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text),
            ],

            GET_YT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube)],
            GET_PLAYLIST:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_playlist)],
            GET_AUDIO:       [MessageHandler((filters.AUDIO | filters.VOICE | DOC_AUDIO_FILTER), handle_audio)],
            GET_SNIPPET:     [MessageHandler((filters.VOICE | filters.AUDIO | DOC_AUDIO_FILTER), handle_snippet)],
            GET_RATING:      [CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:[1-5]$")],
            GET_ALG:         [CallbackQueryHandler(handle_algvote_cb, pattern=r"^alg:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_error_handler(on_error)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
