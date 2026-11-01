"""
Router — menentukan apakah query user butuh RAG (informasi/kebijakan)
atau tool call (aksi spesifik, misal cek status tiket).

Pola ini mengikuti workflow router yang sudah dipelajari di Sesi 12.4:
  user input -> intent detection -> jika butuh data -> retrieval (RAG)
                                  -> jika butuh aksi -> tool call
"""

import re
import time

from app.rag import answer_from_knowledge_base
from app.tools import get_ticket_status

# Kriteria intent 'ticket_status' (keyword baseline):
#   1. query memuat pola ticket_id (TICKET-XXXX / tiket 42), ATAU
#   2. query menyebut kata "tiket"/"ticket" SEKALIGUS (kata kerja pengecekan
#      [status, cek, check, periksa, lacak] ATAU penanda possessif [tiket saya, tiketku, my ticket]).
# Selain itu intent = 'faq' — biarkan RAG/LLM yang menilai ada tidaknya jawaban.
_TICKET_ID_RE = re.compile(r"(?:ticket|tiket)[-\s#]?(\d{1,6})", re.IGNORECASE)
_TICKET_WORD_RE = re.compile(r"\b(?:ticket|tiket)\b", re.IGNORECASE)
_CHECK_ACTION_WORDS = ("status", "cek", "check", "periksa", "lacak")
_POSSESSIVE_RE = re.compile(
    r"\b(?:ticket|tiket)\s*(?:saya|ku|gue|gw|q)\b|\bmy\s+(?:ticket|tiket)\b",
    re.IGNORECASE,
)


async def detect_intent(query: str) -> str:
    """
    Menentukan intent dari query user. Mengembalikan salah satu:
      - "faq"           -> pertanyaan informasi/kebijakan, arahkan ke RAG
      - "ticket_status" -> permintaan cek status tiket, arahkan ke tool call

    Baseline berbasis keyword (deterministik, tanpa call API tambahan).
    """
    if _TICKET_ID_RE.search(query):
        return "ticket_status"

    query_lower = query.lower()
    mentions_ticket = _TICKET_WORD_RE.search(query) is not None
    wants_check = any(word in query_lower for word in _CHECK_ACTION_WORDS)
    possessive = _POSSESSIVE_RE.search(query) is not None

    if mentions_ticket and (wants_check or possessive):
        return "ticket_status"

    return "faq"


async def handle_query(query: str) -> dict:
    """
    Dipanggil endpoint /ask. Mendeteksi intent lalu merutekan ke RAG atau tool call.
    Mengembalikan dict yang menyertakan 'meta' (timing/token) untuk evaluasi.
    """
    intent = await detect_intent(query)

    if intent == "ticket_status":
        ticket_id = extract_ticket_id(query)
        t0 = time.perf_counter()
        data = get_ticket_status(ticket_id)
        lookup_ms = (time.perf_counter() - t0) * 1000
        return {
            "status": "success",
            "intent": "ticket_status",
            "data": data,
            "meta": {"lookup_ms": round(lookup_ms, 1), "total_tokens": None},
        }

    elif intent == "faq":
        data, meta = await answer_from_knowledge_base(query)
        return {"status": "success", "intent": "faq", "data": data, "meta": meta}

    else:
        return {
            "status": "error",
            "intent": "unknown",
            "data": "Maaf, saya tidak memahami permintaan Anda.",
            "meta": {},
        }


def extract_ticket_id(query: str) -> str:
    """
    Ekstraksi ticket_id dari teks query.
    Format ticket_id pada mock_tickets.csv adalah 'TICKET-XXXX'.
    Mengembalikan string kosong jika tidak ada pola ticket_id di query.
    """
    match = _TICKET_ID_RE.search(query)
    if not match:
        return ""
    return f"TICKET-{int(match.group(1)):04d}"
