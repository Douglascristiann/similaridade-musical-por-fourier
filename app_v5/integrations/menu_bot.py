# app_v5/integrations/menu_bot.py
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
    criar_tabela, upsert_usuario, upsert_nps, update_nps_algoritmo,
    fetch_random_negatives, inserir_user_test_pair, inserir_user_test_nps,
    update_user_test_pair_score
)
from .bridge import (
    recommend_from_audio_file, recommend_from_youtube, list_db,
    process_playlist_youtube, recalibrate
)
from .shazam_flow import recognize_and_pick_youtube

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Carrega variáveis de ambiente (ex.: BOT_TOKEN) do .env ao lado deste arquivo
load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))

# ---------- Estados ----------
(
    REGISTER_NAME, REGISTER_EMAIL, REGISTER_STREAM, MENU, GET_YT, GET_AUDIO, GET_SNIPPET,
    GET_PLAYLIST, GET_RATING, GET_ALG,
    UT_CONSENT, UT_VOTE, UT_LIKERT, UT_NPS, UT_COMMENT
) = range(15)

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
    "8) Teste com usuário (lista cega)\n"
    "0) Sair"
)

def _stream_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl, callback_data=f"s_{key}")] for key, lbl in STREAM_CHOICES
    ])

def _menu_kb():
    # Espelha o menu com botões
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1) Áudio local", callback_data="m_1"),
         InlineKeyboardButton("2) Link YouTube", callback_data="m_2")],
        [InlineKeyboardButton("3) Upload em massa (CLI)", callback_data="m_3")],
        [InlineKeyboardButton("4) Recalibrar & Recomendar", callback_data="m_4")],
        [InlineKeyboardButton("5) Playlist YouTube (bulk)", callback_data="m_5")],
        [InlineKeyboardButton("6) Listar últimos", callback_data="m_6")],
        [InlineKeyboardButton("7) Trecho (Shazam)", callback_data="m_7")],
        [InlineKeyboardButton("8) Teste com usuário", callback_data="m_8")],
        [InlineKeyboardButton("0) Sair", callback_data="m_0")],
    ])

# ---------- Formatadores (texto puro) ----------
def _fmt_items_text(items: list[dict]) -> str:
    """Renderiza recomendações em texto simples."""
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
    """Listagem simples de itens no banco."""
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
        [InlineKeyboardButton("⭐ 0", callback_data="rate:0"),
         InlineKeyboardButton("⭐ 1", callback_data="rate:1"),
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

# ---------- Teclados do Teste com Usuário ----------
def _kb_ut_consent():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Topo", callback_data="ut:consent:ok"),
        InlineKeyboardButton("⏳ Agora não", callback_data="ut:consent:no"),
    ]])

def _kb_ut_yes_no_skip():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="ut:sim"),
        InlineKeyboardButton("❌ Não", callback_data="ut:nao"),
        InlineKeyboardButton("⏭️ Pular", callback_data="ut:skip"),
    ]])

def _kb_ut_likert():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data="ut:likert:1"),
         InlineKeyboardButton("2", callback_data="ut:likert:2"),
         InlineKeyboardButton("3", callback_data="ut:likert:3"),
         InlineKeyboardButton("4", callback_data="ut:likert:4"),
         InlineKeyboardButton("5", callback_data="ut:likert:5")],
        [InlineKeyboardButton("⏭️ Pular", callback_data="ut:likert:skip")]
    ])

def _kb_ut_nps():
    row1 = [InlineKeyboardButton(str(i), callback_data=f"ut:nps:{i}") for i in range(0,6)]
    row2 = [InlineKeyboardButton(str(i), callback_data=f"ut:nps:{i}") for i in range(6,11)]
    return InlineKeyboardMarkup([row1, row2])

# ---------- Preferência de identificador do usuário ----------
def _user_ref(context: ContextTypes.DEFAULT_TYPE):
    """Retorna o identificador preferencial do usuário para o DB (id AI; fallback: email)."""
    return context.user_data.get("user_pk") or context.user_data.get("email")

# ---------- Util: edição resiliente ----------
async def safe_edit(q, text: str, **kwargs):
    """
    Tenta editar a mensagem do callback. Em caso de erro de rede, envia nova mensagem.
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
    allowed = {k: v for k, v in kwargs.items() if k in {"reply_markup", "disable_web_page_preview", "parse_mode"}}
    return await q.message.reply_text(text, **allowed)

# ---------- Fluxo de cadastro ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_tabela()  # garante tb_usuarios / tb_nps etc.
    await update.message.reply_text(
        "🎵 Bem-vindo ao FourierMatch!\n\n"
        "Aqui você encontra músicas parecidas de verdade!\n"
        "Nosso sistema entende a melodia e as frequências do som para recomendar faixas que combinam com o que você curte.\n\n"
        "👇🏼 Para começar, qual é o seu nome completo? 👇🏼"
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
    fullname = context.user_data.get("fullname", "")
    email = context.user_data.get("email", "")

    await safe_edit(q, "Processando cadastro…")

    loop = asyncio.get_running_loop()
    try:
        pk = await loop.run_in_executor(None, upsert_usuario, None, fullname, email, pref)
        context.user_data["user_pk"] = int(pk)  # guarda o id autoincrementado
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
    if data == "m_8":
        # Inicia Teste com Usuário (usa última recomendação feita)
        await safe_edit(q,
            "Vamos fazer um teste rápido de similaridade musical. Você topa participar? (leva ~3–5 min)\n\n"
            "• Use **fone de ouvido**\n"
            "• Você ouvirá 6 faixas (3 recomendadas + 3 fora da recomendação) e dirá se **soam similares** à música de referência (seed)\n",
            parse_mode="Markdown",
            reply_markup=_kb_ut_consent()
        ); return UT_CONSENT
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
    if text == "8":
        await update.message.reply_text(
            "Vamos fazer um teste rápido de similaridade musical. Você topa participar? (leva ~3–5 min)\n\n"
            "• Use **fone de ouvido**\n"
            "• Você ouvirá 6 faixas (3 recomendadas + 3 fora da recomendação) e dirá se **soam similares** à música de referência (seed)\n",
            parse_mode="Markdown",
            reply_markup=_kb_ut_consent()
        ); return UT_CONSENT
    if text == "0" or text.lower() in {"sair","exit","quit"}:
        await update.message.reply_text("Sessão encerrada. 👋"); return ConversationHandler.END
    await update.message.reply_text("Envie uma opção válida do menu (0..8) ou use os botões abaixo.", reply_markup=_menu_kb())
    return MENU

# ---------- Handlers de ações (YouTube/Áudio/Snippet/Playlist) ----------
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
    await update.message.reply_text(
        "Como você avalia esse resultado? De 0 a 5 — 0 = nada provável ... 5 = extremamente provável.",
        reply_markup=_rating_kb()
    )
    return GET_RATING

async def handle_playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    await update.message.reply_text("⏳ Baixando itens da playlist e processando…")
    loop = asyncio.get_running_loop()
    try:
        r = await loop.run_in_executor(None, process_playlist_youtube, text, SR_DEFAULT)
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
    await update.message.reply_text(
        "Como você avalia esse resultado? De 0 a 5 — 0 = nada provável ... 5 = extremamente provável.",
        reply_markup=_rating_kb()
    )
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
            await msg.reply_text(
                "Como você avalia esse resultado? De 0 a 5 — 0 = nada provável ... 5 = extremamente provável.",
                reply_markup=_rating_kb()
            )
            return GET_RATING
        else:
            await msg.reply_text(f"❌ Erro ao recomendar: {rec.get('message')}", reply_markup=_menu_kb()); return MENU
    else:
        await msg.reply_text("❌ Não foi possível construir destino do YouTube.", reply_markup=_menu_kb()); return MENU

# ---------- Pós-ação: coleta de NPS (0..5) e voto de algoritmo ----------
async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^rate:(\d)$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida.", reply_markup=_menu_kb()); 
        return MENU

    rating = int(m.group(1))
    payload = context.user_data.get("last_rate_payload") or {}

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
    """
    Após o voto de plataforma: registra e INICIA automaticamente o Teste com Usuário (lista cega).
    """
    q = update.callback_query
    await q.answer()
    m = re.match(r"^alg:(.+)$", q.data or "")
    choice = (m.group(1) if m else "=")
    payload = context.user_data.get("last_rate_payload") or {}

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

    # 🔁 Em vez de voltar ao menu, engata o Teste com Usuário
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass

    await q.message.reply_text(
        "Antes de finalizar, topa responder um teste rápido de similaridade? (leva ~3–5 min)\n\n"
        "• Use **fone de ouvido**\n"
        "• Você ouvirá 6 faixas (3 recomendadas + 3 fora da recomendação) e dirá se **soam similares** à música de referência (seed)\n",
        parse_mode="Markdown",
        reply_markup=_kb_ut_consent()
    )
    # NÃO limpar o last_rate_payload aqui — ele é usado como seed para a lista cega
    return UT_CONSENT

# ===================== Fluxo: Teste com usuário (lista cega) =====================
async def ut_consent_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if (q.data or "") == "ut:consent:no":
        await safe_edit(q, "Tudo bem! Quando quiser, é só voltar ao menu.", reply_markup=_menu_kb())
        return MENU
    if (q.data or "") != "ut:consent:ok":
        await safe_edit(q, "Entrada inválida.", reply_markup=_menu_kb()); 
        return MENU

    # Precisa de uma recomendação feita antes (para usar Top-k atual)
    payload = context.user_data.get("last_rate_payload")
    if not payload or not isinstance(payload.get("result_json"), dict):
        await safe_edit(q,
            "⚠️ Para o teste, faça primeiro uma recomendação (opção 1, 2 ou 7).\n"
            "Depois volte na opção 8) Teste com usuário.",
            reply_markup=_menu_kb()
        ); 
        return MENU

    res = payload["result_json"]
    query = res.get("query") or {}
    items = res.get("items") or []
    if not items:
        await safe_edit(q, "Não encontrei Top-k desta sessão. Gere uma recomendação e tente novamente.",
                        reply_markup=_menu_kb()); 
        return MENU

    # === MONTA LISTA CEGA: Top-3 recomendadas + 3 negativas (com link) ===
    k = min(3, len(items))
    top = []
    for it in items[:k]:
        top.append({
            "id": int(it.get("id") or 0),
            "titulo": (it.get("titulo") or "").strip(),
            "artista": (it.get("artista") or "").strip(),
            "in_topk": 1,
            "link": (it.get("link") or "").strip()
        })

    excl = [x["id"] for x in top] + ([int(query.get("id"))] if query.get("id") else [])
    neg_raw = fetch_random_negatives(3, excluir_ids=excl)
    negs = []
    for (cid, t, a, link_sp, link_yt) in neg_raw:
        negs.append({
            "id": int(cid),
            "titulo": t or "",
            "artista": a or "",
            "in_topk": 0,
            "link": (link_sp or link_yt or "").strip()
        })

    blind = top + negs
    import random as _rnd
    _rnd.shuffle(blind)

    # Guarda estado do teste
    context.user_data["ut_state"] = {
        "participant_id": f'U{update.effective_user.id}',
        "seed_id": int(query.get("id") or 0) if query.get("id") else None,
        "seed_title": f"{(query.get('titulo') or query.get('title') or 'Seed')}"
                      f"{(' — ' + (query.get('artista') or '')) if (query.get('artista')) else ''}",
        "items": blind,
        "idx": 0,
        "last_pair_row_id": None,
        "awaiting_comment": False,
        "nps_score": None
    }

    seed_title = context.user_data["ut_state"]["seed_title"] or "Seed"
    await safe_edit(q, f"Seed: *{seed_title}*\nQuando estiver pronto, vamos começar!", parse_mode="Markdown")
    return await ut_send_next(update, context)

async def ut_send_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = (update.effective_chat.id if update.effective_chat 
               else update.callback_query.message.chat.id)
    st = context.user_data.get("ut_state")
    if not st:
        await context.bot.send_message(chat_id, "Sessão de teste não encontrada. Volte ao menu.", reply_markup=_menu_kb())
        return MENU

    idx = st["idx"]
    items = st["items"]
    if idx >= len(items):
        await context.bot.send_message(chat_id, "Obrigado! Agora, uma pergunta final de satisfação (NPS).")
        await context.bot.send_message(chat_id, "De 0 a 10, o quanto você recomendaria o sistema para um amigo?",
                                       reply_markup=_kb_ut_nps())
        return UT_NPS

    c = items[idx]
    titulo = c.get("titulo") or "(sem título)"
    artista = c.get("artista") or ""
    link = c.get("link") or ""
    msg = f"🔊 *{titulo}* — {artista}\n"
    if link:
        msg += f"{link}\n"
    msg += "Soa similar à *seed*?"
    await context.bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=_kb_ut_yes_no_skip())
    return UT_VOTE

async def ut_vote_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data not in {"ut:sim","ut:nao","ut:skip"}:
        await safe_edit(q, "Entrada inválida."); 
        return UT_VOTE

    st = context.user_data.get("ut_state")
    if not st:
        await safe_edit(q, "Sessão de teste encerrada. Volte ao menu.", reply_markup=_menu_kb()); 
        return MENU

    idx = st["idx"]
    items = st["items"]
    if idx >= len(items):
        await safe_edit(q, "Itens concluídos."); 
        return UT_NPS

    c = items[idx]

    # Se respondeu Sim/Não, grava par e pergunta força 1–5
    if data in {"ut:sim","ut:nao"}:
        user_sim = 1 if data == "ut:sim" else 0
        try:
            row_id = inserir_user_test_pair(
                participant_id=st["participant_id"],
                seed_id=st["seed_id"],
                seed_title=st["seed_title"],
                cand_id=int(c["id"]),
                cand_title=f"{c.get('titulo','')} — {c.get('artista','')}".strip(" —"),
                in_topk=int(c["in_topk"]),
                user_sim=int(user_sim),
            )
            st["last_pair_row_id"] = int(row_id)
        except Exception as e:
            log.warning("Falha ao gravar par do user test: %s", e)
            st["last_pair_row_id"] = None

        # pergunta 1–5 (opcional)
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        await q.message.reply_text(
            "De 1 a 5, **quão parecido** você achou?",
            parse_mode="Markdown",
            reply_markup=_kb_ut_likert()
        )
        return UT_LIKERT

    # Se pulou, avança direto para o próximo item
    st["idx"] += 1
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass
    return await ut_send_next(update, context)

async def ut_likert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if not data.startswith("ut:likert:"):
        await safe_edit(q, "Entrada inválida.")
        return UT_LIKERT

    score_tok = data.split(":")[-1]
    st = context.user_data.get("ut_state")
    if not st:
        await safe_edit(q, "Sessão de teste encerrada.", reply_markup=_menu_kb())
        return MENU

    # Atualiza a linha do par com o score 1–5 (se houver row_id)
    if score_tok.isdigit():
        try:
            if st.get("last_pair_row_id"):
                update_user_test_pair_score(int(st["last_pair_row_id"]), int(score_tok))
        except Exception as e:
            log.warning("Falha ao atualizar user_sim_score: %s", e)
    # Se 'skip', não atualiza

    # Limpa e avança para a próxima candidata
    st["last_pair_row_id"] = None
    st["idx"] += 1
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass
    return await ut_send_next(update, context)

async def ut_nps_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not (q.data or "").startswith("ut:nps:"):
        await safe_edit(q, "Entrada inválida."); 
        return UT_NPS
    score = int(q.data.split(":")[2])
    st = context.user_data.get("ut_state")
    if not st:
        await safe_edit(q, "Sessão de teste encerrada.", reply_markup=_menu_kb()); 
        return MENU

    st["nps_score"] = score
    st["awaiting_comment"] = True
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass
    await q.message.reply_text("Obrigado! Deixe um comentário (opcional). Envie em uma única mensagem.\nOu digite /pular para finalizar sem comentário.")
    return UT_COMMENT

async def ut_comment_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = context.user_data.get("ut_state")
    if not st or not st.get("awaiting_comment"):
        return  # ignora textos fora do fluxo
    comment = (update.message.text or "").strip()
    try:
        inserir_user_test_nps(
            participant_id=st["participant_id"],
            seed_id=st["seed_id"],
            seed_title=st["seed_title"],
            nps_score=int(st["nps_score"]),
            nps_comment=comment if comment else None
        )
    except Exception as e:
        log.warning("Falha ao gravar NPS do user test: %s", e)
    st["awaiting_comment"] = False
    await update.message.reply_text("✅ Avaliação concluída. Obrigado! 🙌")
    await update.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

async def ut_comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = context.user_data.get("ut_state")
    if not st:
        await update.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb()); 
        return MENU
    if st.get("awaiting_comment"):
        try:
            inserir_user_test_nps(
                participant_id=st["participant_id"],
                seed_id=st["seed_id"],
                seed_title=st["seed_title"],
                nps_score=int(st["nps_score"]),
                nps_comment=None
            )
        except Exception as e:
            log.warning("Falha ao gravar NPS (sem comentário): %s", e)
        st["awaiting_comment"] = False
        await update.message.reply_text("✅ Avaliação concluída. Obrigado! 🙌")
    await update.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

# ---------- Cancel & Erros ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sessão cancelada. 👋")
    return ConversationHandler.END

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
            GET_RATING:      [CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:[0-5]$")],
            GET_ALG:         [CallbackQueryHandler(handle_algvote_cb, pattern=r"^alg:")],

            # =============== NOVOS ESTADOS DO TESTE COM USUÁRIO ===============
            UT_CONSENT: [
                CallbackQueryHandler(ut_consent_cb, pattern=r"^ut:consent:(ok|no)$")
            ],
            UT_VOTE: [
                CallbackQueryHandler(ut_vote_cb, pattern=r"^ut:(sim|nao|skip)$")
            ],
            UT_LIKERT: [
                CallbackQueryHandler(ut_likert_cb, pattern=r"^ut:likert:(\d|skip)$")
            ],
            UT_NPS: [
                CallbackQueryHandler(ut_nps_cb, pattern=r"^ut:nps:\d+$")
            ],
            UT_COMMENT: [
                CommandHandler("pular", ut_comment_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ut_comment_text)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_error_handler(on_error)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
