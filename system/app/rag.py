"""
Modul RAG — mengubah knowledge base menjadi embedding, menyimpannya ke FAISS,
melakukan semantic search, lalu menghasilkan jawaban menggunakan LLM.

Alur ini serupa dengan yang sudah dibangun di Assignment 3 (Semantic Search &
LLM Application) dan Sesi 11 (Building a Simple RAG System) — di assignment ini,
alur tersebut dibungkus menjadi fungsi yang dipanggil oleh router.py.
"""

import os
import time
from pathlib import Path

import pandas as pd
import numpy as np
import faiss
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-3.5-flash-lite"
TEMPERATURE = 0.3
RELEVANCE_THRESHOLD = 0.60  # jarak L2; relevan <=0.48, tidak relevan >=0.69 (terukur)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
KNOWLEDGE_BASE_PATH = DATA_DIR / "it_helpdesk_knowledge_base.csv"

_index = None
_documents = None
_df = None
_client = None


def _get_client() -> genai.Client:
    """Client Gemini dibuat lazy supaya aplikasi tetap bisa start saat API key
    belum dikonfigurasi — kegagalannya baru muncul sebagai response error di /ask."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY belum diatur di environment variable.")
        _client = genai.Client(api_key=api_key)
    return _client


def _get_embedding(text: str):
    result = _get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def build_index():
    """
    Membangun index FAISS dari knowledge base CSV.
    Referensi: starter_notebook_semantic_search.ipynb Assignment 3, Section 1-4
    (load data -> unit retrievable -> embedding -> simpan ke FAISS).
    Dipanggil satu kali saat aplikasi startup, bukan di setiap request.
    """
    global _index, _documents, _df

    _df = pd.read_csv(KNOWLEDGE_BASE_PATH)
    _df["content"] = "Q: " + _df["question"] + " A: " + _df["answer"]
    _documents = _df["content"].tolist()

    embeddings = np.array(
        [_get_embedding(doc) for doc in _documents], dtype="float32"
    )

    _index = faiss.IndexFlatL2(embeddings.shape[1])
    _index.add(embeddings)

    if _index.ntotal != len(_df):
        raise RuntimeError(
            f"Jumlah vektor di index ({_index.ntotal}) tidak sama dengan "
            f"jumlah entri knowledge base ({len(_df)})."
        )

    print(f"Index FAISS siap: {_index.ntotal} vektor, dimensi {embeddings.shape[1]}")
    return _index


def semantic_search(query: str, top_k: int = 3):
    """
    Semantic search terhadap index yang sudah dibangun.
    Referensi: starter_notebook_semantic_search.ipynb, Section 5.
    Mengembalikan (results, elapsed_ms) - elapsed_ms untuk analisis latency
    """
    if _index is None:
        raise RuntimeError("Index FAISS belum dibangun — build_index() belum dijalankan.")

    t0 = time.perf_counter()
    query_embedding = np.array([_get_embedding(query)], dtype="float32")
    distances, indices = _index.search(query_embedding, top_k)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    results = []
    for rank, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        results.append(
            {
                "rank": rank + 1,
                "question": _df.iloc[idx]["question"],
                "answer": _df.iloc[idx]["answer"],
                "category": _df.iloc[idx]["category"],
                "distance": float(distances[0][rank]),
            }
        )
    return results, elapsed_ms


def _build_prompt(query: str, search_results: list) -> str:
    """Susun prompt untuk LLM. Jika konteks kosong (tidak ada FAQ yang melewati
    RELEVANCE_THRESHOLD), alihkan ke instruksi out-of-scope yang jujur tanpa
    menyuntik konteks tak relevan (menghemat token). Jika konteks ada, dorong
    partial answering: jawab bagian yang tercakup, sebut spesifik yang hilang."""
    if not search_results:
        context = "(Tidak ada konteks yang cukup relevan di knowledge base.)"
        task = (
            "Knowledge base tidak berisi informasi yang relevan dengan pertanyaan ini. "
            "Jika pengguna menyapa, balas sapaan dengan singkat dan tawarkan bantuan terkait "
            "kebijakan IT perusahaan. Jika pengguna bertanya di luar cakupan kebijakan IT, "
            "katakan dengan jujur bahwa informasi tidak tersedia dan sarankan menghubungi tim "
            "IT Helpdesk. Jangan mengarang informasi dari pengetahuan umum."
        )
    else:
        context = "\n\n".join(
            f"FAQ {r['rank']}: {r['question']}\nJawaban: {r['answer']}"
            for r in search_results
        )
        task = (
            "Jawab setiap bagian pertanyaan karyawan yang bisa dijawab dari Context di bawah, "
            "hanya berdasarkan Context. Jika ada bagian pertanyaan yang tidak tercakup dalam "
            "Context, sebutkan secara spesifik bagian mana yang tidak tersedia — jangan mengarang "
            "bagian tersebut dari pengetahuan umum."
        )

    return f"""Persona: Kamu adalah asisten IT Helpdesk internal yang ramah dan profesional.

Task: {task}

Context:
{context}

Format: Jawab dalam bahasa Indonesia yang natural dan ringkas (2-4 kalimat atau langkah singkat), langsung menjawab pertanyaan. Jangan menambahkan informasi di luar Context.

Pertanyaan karyawan: {query}

Jawaban:"""


async def answer_from_knowledge_base(query: str) -> tuple:
    """
    Dipanggil router.py ketika intent = 'faq'.
    Mengembalikan (jawaban, meta) di mana meta berisi timing per-stage dan
    token usage — untuk keperluan evaluasi (bukan mengubah perilaku jawaban).
    """
    search_results, retrieval_ms = semantic_search(query)
    relevant = [r for r in search_results if r["distance"] <= RELEVANCE_THRESHOLD]
    prompt = _build_prompt(query, relevant)

    t0 = time.perf_counter()
    response = await _get_client().aio.models.generate_content(
        model=GENERATION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=TEMPERATURE),
    )
    llm_ms = (time.perf_counter() - t0) * 1000

    usage = getattr(response, "usage_metadata", None)
    meta = {
        "retrieval_ms": round(retrieval_ms, 1),
        "llm_ms": round(llm_ms, 1),
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "completion_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
        "top_k": 3,
        "context_used": len(relevant),
    }
    return response.text, meta
