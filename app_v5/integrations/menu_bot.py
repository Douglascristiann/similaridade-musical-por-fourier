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
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from pydub import AudioSegment
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import TimedOut, RetryAfter, NetworkError, BadRequest
from telegram.request import HTTPXRequest
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

from app_v5.database.db import (
    criar_tabela, upsert_usuario, upsert_nps, update_nps_algoritmo,
    fetch_random_negatives, inserir_user_test_pair, update_user_test_pair_score, inserir_user_test_nps
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
# Adicionado novo estado para o menu de administração
(
    REGISTER_NAME, REGISTER_EMAIL, REGISTER_STREAM, MENU,
    GET_YT, GET_AUDIO, GET_SNIPPET, GET_PLAYLIST,
    GET_RATING, GET_ALG,
    UT_PAIR, UT_SCORE, UT_NPS_SCORE, UT_NPS_COMMENT,
    GET_ADM_PASS, ADM_MENU
) = range(16)

K_DEFAULT = int(os.getenv("BOT_K", "3"))
SR_DEFAULT = int(os.getenv("BOT_SR", "22050"))
# Senha de administração
ADMIN_PASS = "fft#admin"

STREAM_CHOICES = [
    ("spotify",    "Spotify"),
    ("youtube",    "YouTube Music"),
    ("applemusic", "Apple Music"),
    ("deezer",     "Deezer"),
    ("other",      "Outra")
]

# Modificado para incluir a opção de administração
CLI_MENU_TEXT = (
    "🎧  === Menu Principal ===\n"
    "1) Processar áudio local\n"
    "2) Processar link do YouTube\n"
    "7) Reconhecer trecho de áudio (Shazam)\n"
    "A) Acessar área de ADM\n"
    "0) Sair"
)

# Novo menu de administração
ADMIN_MENU_TEXT = (
    "⚙️ === Menu de Administração ===\n"
    "3) Upload em massa (pasta local)\n"
    "4) Recalibrar & Recomendar\n"
    "5) Playlist do YouTube (bulk)\n"
    "6) Listar últimos itens do banco\n"
    "B) Voltar ao menu principal"
)

def _stream_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl, callback_data=f"s_{key}")] for key, lbl in STREAM_CHOICES
    ])

# Teclado do menu principal modificado
def _menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1) Áudio local", callback_data="m_1"),
         InlineKeyboardButton("2) Link YouTube", callback_data="m_2")],
        [InlineKeyboardButton("7) Trecho (Shazam)", callback_data="m_7")],
        [InlineKeyboardButton("A) ADM", callback_data="m_adm")],
        [InlineKeyboardButton("0) Sair", callback_data="m_0")],
    ])

# Novo teclado para o menu de administração
def _adm_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("3) Upload em massa (CLI)", callback_data="adm_3")],
        [InlineKeyboardButton("4) Recalibrar & Recomendar", callback_data="adm_4")],
        [InlineKeyboardButton("5) Playlist YouTube (bulk)", callback_data="adm_5")],
        [InlineKeyboardButton("6) Listar últimos", callback_data="adm_6")],
        [InlineKeyboardButton("B) Voltar", callback_data="adm_back")],
    ])


# ---------- Formatadores ----------
def _best_link(item: Dict[str, Any]) -> str:
    # item pode ser do resultado ou uma linha da tb_musicas
    return item.get("link") or item.get("spotify") or item.get("youtube") or ""

# ALTERAÇÃO: Função modificada para exibir medalhas em vez de porcentagem
def _fmt_items_text(items: list[dict]) -> str:
    if not items:
        return "*Nenhuma recomendação encontrada\\.*"
    
    lines = ["*🎯 Recomendações:*", ""]
    medals = ["🥇", "🥈", "🥉"]
    
    for i, it in enumerate(items, 1):
        link = _best_link(it)
        titulo_esc = escape_markdown((it.get("titulo") or "").replace("\n", " ").strip(), version=2)
        artista_esc = escape_markdown((it.get("artista") or "").replace("\n", " ").strip(), version=2)
        
        # Define o prefixo como medalha para os 3 primeiros, ou número para os demais
        if i <= len(medals):
            prefix = medals[i-1]
        else:
            prefix = f"{i}\\."
        
        # Constrói a linha sem a porcentagem de similaridade
        line = f"{prefix} {titulo_esc} — {artista_esc}"
        
        if link:
            # Formata como um hyperlink clicável
            escaped_link_text = escape_markdown(link, version=2)
            line += f"\n   [{escaped_link_text}]({link})"
        lines.append(line)
        
    return "\n".join(lines)


def _fmt_table_rows_text(rows: list[dict]) -> str:
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

def _yesno_kb(idx: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim", callback_data=f"ut:pair:{idx}:1"),
         InlineKeyboardButton("❌ Não", callback_data=f"ut:pair:{idx}:0")]
    ])

def _likert_1_5_kb(row_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data=f"ut:score:{row_id}:1"),
         InlineKeyboardButton("2", callback_data=f"ut:score:{row_id}:2"),
         InlineKeyboardButton("3", callback_data=f"ut:score:{row_id}:3"),
         InlineKeyboardButton("4", callback_data=f"ut:score:{row_id}:4"),
         InlineKeyboardButton("5", callback_data=f"ut:score:{row_id}:5")]
    ])

def _nps_0_10_kb():
    # Duas linhas para garantir que todos (0..10) apareçam em qualquer cliente
    row1 = [InlineKeyboardButton(str(i), callback_data=f"ut:nps:{i}") for i in range(0, 6)]   # 0..5
    row2 = [InlineKeyboardButton(str(i), callback_data=f"ut:nps:{i}") for i in range(6, 11)]  # 6..10
    return InlineKeyboardMarkup([row1, row2])

def _skip_comment_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Pular comentário", callback_data="ut:nps_skip")]
    ])

def _fmt_list(items: List[Dict[str, Any]], titulo: str) -> str:
    lines = [f"*{escape_markdown(titulo, version=2)}*"]
    for it in items:
        t = escape_markdown((it.get("titulo") or "").strip(), version=2)
        a = escape_markdown((it.get("artista") or "").strip(), version=2)
        link = it.get("link") or ""
        bullet = f"• {t} — {a}"
        if link:
            escaped_link_text = escape_markdown(link, version=2)
            bullet += f"\n  [{escaped_link_text}]({link})"
        lines.append(bullet)
    return "\n".join(lines)

# ---------- Preferência de identificador do usuário ----------
def _user_ref(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.get("user_pk") or context.user_data.get("email")

# ---------- Util: edição resiliente ----------
async def safe_edit(q, text: str, **kwargs):
    try:
        return await q.edit_message_text(text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 2))
        try:
            return await q.edit_message_text(text, **kwargs)
        except (BadRequest, TimedOut, NetworkError):
             pass # Ignora erros se a segunda tentativa falhar
    except (BadRequest, TimedOut, NetworkError):
        pass
    allowed = {k: v for k, v in kwargs.items() if k in {"reply_markup", "disable_web_page_preview", "parse_mode"}}
    return await q.message.reply_text(text, **allowed)

# ---------- Fluxo de cadastro ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_tabela()
    await update.message.reply_text(
        "🎵 Bem-vindo ao FourierMatch!\n\n"
        "Aqui você encontra músicas parecidas de verdade.\n"
        "👇🏼Para começar, qual é o seu nome completo?"
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
        context.user_data["user_pk"] = int(pk)
    except Exception as e:
        await q.message.reply_text(f"⚠️ Erro ao salvar cadastro: {e}")
        await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
        return MENU

    await safe_edit(q, "Cadastro concluído ✅")
    await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb())
    return MENU

# ---------- Menu ----------
async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "m_1":
        await safe_edit(q, "Envie um áudio (voice, .mp3, .wav...)."); return GET_AUDIO
    if data == "m_2":
        await safe_edit(q, "Envie o link do YouTube (vídeo único)."); return GET_YT
    if data == "m_7":
        await safe_edit(q, "Envie um trecho de áudio (até 30s)."); return GET_SNIPPET
    if data == "m_adm":
        await safe_edit(q, "Digite a senha de administrador."); return GET_ADM_PASS
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
    if text == "7":
        await update.message.reply_text("Envie um trecho de áudio (até 30s)."); return GET_SNIPPET
    if text.lower() == "a":
        await update.message.reply_text("Digite a senha de administrador."); return GET_ADM_PASS
    if text == "0" or text.lower() in {"sair","exit","quit"}:
        await update.message.reply_text("Sessão encerrada. 👋"); return ConversationHandler.END
    await update.message.reply_text("Envie uma opção válida do menu ou use os botões abaixo.", reply_markup=_menu_kb())
    return MENU

# ---------- Funções de Administração ----------
async def handle_adm_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = (update.message.text or "").strip()
    if password == ADMIN_PASS:
        context.user_data["is_admin"] = True
        await update.message.reply_text(ADMIN_MENU_TEXT, reply_markup=_adm_menu_kb())
        return ADM_MENU
    else:
        await update.message.reply_text("Senha incorreta. Voltando ao menu principal.", reply_markup=_menu_kb())
        return MENU

async def adm_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "adm_3":
        await safe_edit(q, "Opção 3 (Upload em massa) é exclusiva da CLI.", reply_markup=_adm_menu_kb()); return ADM_MENU
    if data == "adm_4":
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
        await q.message.reply_text(ADMIN_MENU_TEXT, reply_markup=_adm_menu_kb()); return ADM_MENU
    if data == "adm_5":
        await safe_edit(q, "Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    if data == "adm_6":
        rows = list_db(limit=20) or []
        if not rows:
            await safe_edit(q, "Banco vazio.", reply_markup=_adm_menu_kb()); return ADM_MENU
        await safe_edit(q, _fmt_table_rows_text(rows), reply_markup=_adm_menu_kb()); return ADM_MENU
    if data == "adm_back":
        await safe_edit(q, CLI_MENU_TEXT, reply_markup=_menu_kb()); return MENU
    await safe_edit(q, ADMIN_MENU_TEXT, reply_markup=_adm_menu_kb())
    return ADM_MENU

async def adm_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "3":
        await update.message.reply_text("Opção 3 (Upload em massa) é exclusiva da CLI.", reply_markup=_adm_menu_kb()); return ADM_MENU
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
        await update.message.reply_text(ADMIN_MENU_TEXT, reply_markup=_adm_menu_kb()); return ADM_MENU
    if text == "5":
        await update.message.reply_text("Envie o link da playlist/álbum (YouTube)."); return GET_PLAYLIST
    if text == "6":
        rows = list_db(limit=20) or []
        if not rows:
            await update.message.reply_text("Banco vazio.", reply_markup=_adm_menu_kb()); return ADM_MENU
        await update.message.reply_text(_fmt_table_rows_text(rows), reply_markup=_adm_menu_kb()); return ADM_MENU
    if text.lower() == "b":
        await update.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb()); return MENU
    await update.message.reply_text("Opção inválida. Use os botões.", reply_markup=_adm_menu_kb())
    return ADM_MENU


# ---------- Handlers principais ----------
async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Envie um link do YouTube."); return GET_YT
    await update.message.reply_text("⏳ Analisando, aguarde… Tempo estimado 2 minutos.")
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, recommend_from_youtube, text, K_DEFAULT, SR_DEFAULT)
    if r.get("status") != "ok":
        await update.message.reply_text(f"❌ Erro: {r.get('message') or 'falha'}", reply_markup=_menu_kb()); return MENU
    q = r.get("query") or {}
    musica_id = int(q.get("id") or 0)
    
    await update.message.reply_text(
        _fmt_items_text(r.get("items") or []), 
        parse_mode=ParseMode.MARKDOWN_V2, 
        disable_web_page_preview=True
    )
    
    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "youtube", "input_ref": text, "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado? (1 a 5)", reply_markup=_rating_kb())
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
    
    await update.message.reply_text(
        _fmt_items_text(r.get("items") or []), 
        parse_mode=ParseMode.MARKDOWN_V2, 
        disable_web_page_preview=True
    )

    context.user_data["last_rate_payload"] = {
        "musica_id": musica_id, "channel": "audio_local", "input_ref": q.get("caminho",""), "result_json": r
    }
    await update.message.reply_text("Como você avalia esse resultado? (1 a 5)", reply_markup=_rating_kb())
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
            
            await msg.reply_text(
                _fmt_items_text(rec.get("items") or []), 
                parse_mode=ParseMode.MARKDOWN_V2, 
                disable_web_page_preview=True
            )
            
            context.user_data["last_rate_payload"] = {
                "musica_id": musica_id, "channel": "snippet", "input_ref": target, "result_json": rec
            }
            await msg.reply_text("Como você avalia esse resultado? (1 a 5)", reply_markup=_rating_kb())
            return GET_RATING
        else:
            await msg.reply_text(f"❌ Erro ao recomendar: {rec.get('message')}", reply_markup=_menu_kb()); return MENU
    else:
        await msg.reply_text("❌ Não foi possível construir destino do YouTube.", reply_markup=_menu_kb()); return MENU

# ---------- Pós-ação: NPS e voto + gatilho do Teste com Usuário ----------
async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^rate:(\d)$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida.", reply_markup=_menu_kb()); return MENU
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
        context.user_data["last_rating_value"] = int(rating)
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

    user_ref = _user_ref(context)
    if not user_ref:
        await safe_edit(q, "Não encontrei seu cadastro nesta sessão. Envie /start para cadastrar e poder votar.",
                        reply_markup=_menu_kb())
        return MENU

    musica_id = int((payload.get("musica_id") or 0))
    last_rating = int(context.user_data.get("last_rating_value") or 3)
    channel = payload.get("channel")
    input_ref = payload.get("input_ref")
    result_json = json.dumps(payload.get("result_json") or {})

    try:
        # Upsert completo para garantir alg_vencedor na MESMA linha do seed
        upsert_nps(
            user_ref=user_ref,
            musica_id=musica_id,
            rating=last_rating,
            channel=channel,
            input_ref=input_ref,
            result_json=result_json,
            alg_vencedor=choice,
        )
        await safe_edit(q, "👍 Voto registrado.")
    except Exception:
        try:
            update_nps_algoritmo(user_ref, musica_id, choice)
            await safe_edit(q, "👍 Voto registrado.")
        except Exception as e2:
            await safe_edit(q, f"⚠️ Erro ao registrar voto: {e2}")
            await q.message.reply_text(CLI_MENU_TEXT, reply_markup=_menu_kb()); return MENU

    # ---- Inicia fluxo do teste com usuário em duas fases ----
    return await start_user_test_flow(update, context)


## --- INÍCIO: Lógica do Teste de Usuário (em duas fases) --- ##
def _seed_info_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    q = payload.get("result_json", {}).get("query") or {}
    # Tenta pegar título e artista; se não existirem, forma um título básico
    seed_title = f"{(q.get('titulo') or '').strip()} — {(q.get('artista') or '').strip()}".strip(" —")
    
    # Se o título ainda estiver vazio (caso do áudio local), usa uma referência alternativa
    if not seed_title:
        # Usa o input_ref (caminho do arquivo) como um identificador reserva
        seed_title = (payload.get("input_ref") or "Áudio Local").split('/')[-1]

    return {
        "seed_id": int(q.get("id") or 0),
        "seed_title": seed_title,
    }

def _top3_from_result(result_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = result_json.get("items") or []
    out = []
    for it in items[:3]:
        out.append({
            "id": int(it.get("id") or 0),
            "titulo": it.get("titulo") or "",
            "artista": it.get("artista") or "",
            "link": it.get("link") or "",
            "in_topk": 1
        })
    return out

async def start_user_test_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prepara Top-3 (fase 1) e 3 negativos (fase 2). Mostra listas separadas."""
    msg = update.effective_message
    payload = context.user_data.get("last_rate_payload") or {}

    # monta listas
    seed = _seed_info_from_payload(payload)
    rec_items = _top3_from_result(payload.get("result_json") or {})
    excluir = [seed["seed_id"]] + [c["id"] for c in rec_items if c["id"]]
    negs = fetch_random_negatives(3, excluir_ids=excluir) or []
    neg_items: List[Dict[str, Any]] = []
    for (nid, ntit, nart, sp, yt) in negs:
        neg_items.append({
            "id": int(nid),
            "titulo": ntit or "",
            "artista": nart or "",
            "link": (sp or yt or ""),
            "in_topk": 0
        })

    if not (rec_items and neg_items):
        await msg.reply_text("⚠️ Não consegui montar os pares do teste agora. Voltando ao menu.", reply_markup=_menu_kb())
        return MENU

    # guarda estado do teste em 2 fases
    context.user_data["ut_state"] = {
        "participant_id": str(context.user_data.get("user_pk") or context.user_data.get("email") or "anon"),
        "seed_id": seed["seed_id"],
        "seed_title": seed["seed_title"],
        "rec_items": rec_items,
        "neg_items": neg_items,
        "rec_idx": 0,
        "neg_idx": 0,
        "phase": "rec",  # 'rec' -> depois 'neg'
        "last_pair_row_id": None,
        "seed_input_ref": payload.get("input_ref"),
        "seed_result_json": json.dumps(payload.get("result_json") or {}),
    }

    # lista 1: recomendadas (antes das perguntas)
    rec_list_text = _fmt_list(rec_items, "Lista de Músicas Recomendadas")
    await msg.reply_text(rec_list_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

    # dispara primeira pergunta da fase 'rec'
    return await ask_current_pair(msg, context)

def _current_phase_and_item(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, Optional[Dict[str, Any]], int, int]:
    """Retorna (phase, item, idx_atual, total_da_fase)."""
    st = context.user_data.get("ut_state") or {}
    phase = st.get("phase") or "rec"
    if phase == "rec":
        items = st.get("rec_items") or []
        idx = int(st.get("rec_idx") or 0)
        item = items[idx] if idx < len(items) else None
        return "rec", item, idx, len(items)
    else:
        items = st.get("neg_items") or []
        idx = int(st.get("neg_idx") or 0)
        item = items[idx] if idx < len(items) else None
        return "neg", item, idx, len(items)

async def ask_current_pair(msg, context: ContextTypes.DEFAULT_TYPE):
    phase, item, idx, total = _current_phase_and_item(context)
    st = context.user_data.get("ut_state") or {}

    if item is None:
        # terminou a fase atual
        if phase == "rec":
            # antes de ir para 'neg', mostre lista das não recomendadas
            neg_items = st.get("neg_items") or []
            neg_list_text = _fmt_list(neg_items, "Lista de Músicas Não Recomendadas")
            await msg.reply_text(neg_list_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
            # muda fase e pergunta o primeiro 'neg'
            st["phase"] = "neg"
            context.user_data["ut_state"] = st
            return await ask_current_pair(msg, context)

        # terminou 'neg' também -> NPS final
        await msg.reply_text(
            "🔚 Quase lá! Agora, numa escala de 0 a 10, qual a probabilidade de você recomendar o FourierMatch a um amigo?",
            reply_markup=_nps_0_10_kb()
        )
        return UT_NPS_SCORE

    cab = "Avaliação (Recomendadas)" if phase == "rec" else "Avaliação (Não Recomendadas)"
    titulo_esc = escape_markdown(item.get('titulo',''), version=2)
    artista_esc = escape_markdown(item.get('artista',''), version=2)
    link = item.get('link') or ""
    
    link_fmt = ""
    if link:
        escaped_link_text = escape_markdown(link, version=2)
        link_fmt = f"🔗 [{escaped_link_text}]({link})"

    txt = (
        f"🎧 *{escape_markdown(cab, version=2)} {idx+1}/{total}*\n"
        f"{titulo_esc} — {artista_esc}\n"
        f"{link_fmt}\n\n"
        f"👉 Você acha que esta música se parece com a que você mandou?"
    ).strip()

    await msg.reply_text(txt, reply_markup=_yesno_kb(idx), parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    return UT_PAIR


async def ut_pair_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^ut:pair:(\d+):([01])$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida.", reply_markup=None); return UT_PAIR
    idx_clicked = int(m.group(1)); user_sim = int(m.group(2))
    st = context.user_data.get("ut_state") or {}

    # valida se índice clicado bate com o índice atual da fase
    cur_phase, item, current_idx, total = _current_phase_and_item(context)
    if idx_clicked != current_idx or item is None:
        await safe_edit(q, "Este item já foi processado ou a resposta está fora de ordem.", reply_markup=None)
        return await ask_current_pair(q.message, context)

    c = item
    try:
        row_id = inserir_user_test_pair(
            user_ref=_user_ref(context),
            participant_id=st.get("participant_id") or "anon",
            seed_id=st.get("seed_id"),
            seed_title=st.get("seed_title"),
            cand_id=int(c["id"]),
            cand_title=f"{c.get('titulo','')} — {c.get('artista','')}".strip(" —"),
            in_topk=int(c.get("in_topk") or (1 if cur_phase == "rec" else 0)),
            user_sim=int(user_sim),
            input_ref=st.get("seed_input_ref"),
            result_json=st.get("seed_result_json"),
        )
        context.user_data["ut_state"]["last_pair_row_id"] = int(row_id)
        await safe_edit(q, "Obrigado! Agora dê uma nota de 1 a 5 para o quão similares são.", reply_markup=_likert_1_5_kb(int(row_id)))
        return UT_SCORE
    except Exception as e:
        log.warning("Falha ao gravar par do user test: %s", e)
        await safe_edit(q, "⚠️ Não consegui salvar este par, mas siga com a próxima avaliação.")
        await q.message.reply_text("Dê uma nota de 1 a 5 para a similaridade:", reply_markup=_likert_1_5_kb(0))
        return UT_SCORE

async def ut_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^ut:score:(\d+):([1-5])$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida."); return UT_PAIR
    row_id = int(m.group(1))
    score = int(m.group(2))

    if row_id > 0:
        try:
            update_user_test_pair_score(row_id, score)
        except Exception as e:
            log.warning("Falha ao gravar score do par: %s", e)

    # avança índice na fase corrente
    st = context.user_data.get("ut_state") or {}
    phase, _, _, _ = _current_phase_and_item(context)
    if phase == "rec":
        st["rec_idx"] = int(st.get("rec_idx", 0)) + 1
    else: # neg
        st["neg_idx"] = int(st.get("neg_idx", 0)) + 1
    context.user_data["ut_state"] = st

    await safe_edit(q, "✅ Registrado!")
    return await ask_current_pair(q.message, context)

async def ut_nps_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^ut:nps:(\d{1,2})$", q.data or "")
    if not m:
        await safe_edit(q, "Entrada inválida."); return MENU
    nps_val = int(m.group(1))
    context.user_data["ut_nps_score"] = nps_val
    await safe_edit(
        q,
        "Valeu! Se quiser, deixe um comentário (opcional) sobre a experiência.\n\n"
        "Digite sua mensagem aqui ou toque em “Pular comentário”.",
        reply_markup=_skip_comment_kb()
    )
    return UT_NPS_COMMENT

async def ut_nps_comment_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = (update.message.text or "").strip()
    if comment == "-":
        comment = None
    
    await _save_nps_and_finish(update.message, context, comment)
    return MENU

async def ut_nps_skip_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Editamos a mensagem para remover o botão "Pular"
    await safe_edit(q, "Obrigado por participar! Processando seu feedback final...")
    await _save_nps_and_finish(q.message, context, None)
    return MENU

async def _save_nps_and_finish(message, context: ContextTypes.DEFAULT_TYPE, comment: Optional[str]):
    st = context.user_data.get("ut_state") or {}
    nps_val = int(context.user_data.get("ut_nps_score") or 0)
    try:
        inserir_user_test_nps(
            user_ref=_user_ref(context),
            participant_id=st.get("participant_id") or "anon",
            seed_id=st.get("seed_id"),
            seed_title=st.get("seed_title"),
            nps_score=nps_val,
            nps_comment=comment
        )
    except Exception as e:
        log.warning("Falha ao gravar NPS do user test: %s", e)

    # limpa estado e volta ao menu
    context.user_data.pop("ut_state", None)
    context.user_data.pop("ut_nps_score", None)
    await message.reply_text("🎉 Obrigado por participar! Voltando ao menu.", reply_markup=_menu_kb())

## --- FIM: Lógica do Teste de Usuário --- ##

# ---------- Cancel & Error ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sessão cancelada. 👋")
    return ConversationHandler.END

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Captura o erro para log, mas evita que o bot pare
    log.error("Unhandled error: %s", context.error, exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Ocorreu um erro temporário. Tente novamente.")
    except Exception as e:
        log.error("Error while sending error message: %s", e)


def main():
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina BOT_TOKEN no ambiente ou em app_v5/integrations/.env")

    request = HTTPXRequest(
        connect_timeout=float(os.getenv("TG_CONNECT_TIMEOUT", 20)),
        read_timeout=float(os.getenv("TG_READ_TIMEOUT", 60)),
        write_timeout=float(os.getenv("TG_WRITE_TIMEOUT", 60)),
        pool_timeout=float(os.getenv("TG_POOL_TIMEOUT", 10)),
    )

    app = Application.builder().token(token).request(request).build()

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
            GET_ADM_PASS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adm_pass)],

            ADM_MENU: [
                CallbackQueryHandler(adm_menu_cb, pattern=r"^adm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_menu_text),
            ],

            GET_RATING:      [CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:[1-5]$")],
            GET_ALG:         [CallbackQueryHandler(handle_algvote_cb, pattern=r"^alg:")],

            # user test flow
            UT_PAIR:         [CallbackQueryHandler(ut_pair_cb, pattern=r"^ut:pair:\d+:[01]$")],
            UT_SCORE:        [CallbackQueryHandler(ut_score_cb, pattern=r"^ut:score:\d+:[1-5]$")],
            UT_NPS_SCORE:    [CallbackQueryHandler(ut_nps_score_cb, pattern=r"^ut:nps:\d{1,2}$")],
            UT_NPS_COMMENT:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ut_nps_comment_msg),
                CallbackQueryHandler(ut_nps_skip_cb, pattern=r"^ut:nps_skip$")
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
