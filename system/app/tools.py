"""
Modul Tools — fungsi-fungsi "aksi" yang dipanggil router ketika intent
BUKAN pertanyaan informasi/kebijakan, melainkan permintaan spesifik
yang butuh pengecekan data langsung (bukan retrieval semantik).

Pola ini mengikuti konsep Tool Integration di Sesi 12.3.
"""

from pathlib import Path

import pandas as pd

MOCK_TICKETS_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_tickets.csv"


def get_ticket_status(ticket_id: str) -> str:
    """
    Mencari status tiket berdasarkan ticket_id pada data mock_tickets.csv.

    Jika ticket_id tidak ditemukan, mengembalikan pesan yang informatif
    (bukan error yang membuat aplikasi crash).
    """
    ticket_id = (ticket_id or "").strip()
    if not ticket_id:
        return (
            "Ticket ID tidak terdapat dalam permintaan Anda. "
            "Sertakan ticket_id dalam format TICKET-XXXX, contoh: TICKET-0002."
        )

    df = pd.read_csv(MOCK_TICKETS_PATH)
    row = df[df["ticket_id"].str.upper() == ticket_id.upper()]

    if row.empty:
        return (
            f"Tiket {ticket_id.upper()} tidak ditemukan di dalam data tiket. "
            "Silakan periksa kembali nomor tiket Anda atau hubungi tim IT Helpdesk."
        )

    ticket = row.iloc[0]
    return (
        f"Tiket {ticket['ticket_id']} — {ticket['subject']}\n"
        f"Karyawan: {ticket['employee_name']} | Kategori: {ticket['category']}\n"
        f"Status: {ticket['status']} (perbaruan terakhir {ticket['last_update']})"
    )
