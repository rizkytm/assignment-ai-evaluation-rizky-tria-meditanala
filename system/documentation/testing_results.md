# Hasil Pengujian — IT Helpdesk Assistant

Pengujian endpoint `POST /ask` dengan 5 skenario sesuai ketentuan brief (langkah 8):
2 query ke RAG, 2 query ke tool call (1 di antaranya ticket_id tidak ada di data),
dan 1 query ambigu/di luar cakupan.

Semua skenario dijalankan dua kali: terhadap server lokal (`uvicorn`) dan terhadap
container Docker (`docker run -p 8000:8000 --env-file .env`), diakses dari luar
container via `curl`. Hasilnya identik.

## Ringkasan

| # | Query | Intent | Komponen | Hasil | Status |
| :-: | :---- | :----- | :------- | :---- | :----- |
| 1 | Berapa jatah cuti tahunan karyawan tetap? | `faq` | RAG | Jawaban sesuai KB (12 hari, masa kerja min. 3 bulan) | Sesuai harapan |
| 2 | gimana cara reset password VPN saya ya? | `faq` | RAG | Parafrase terdeteksi, jawaban sesuai KB | Sesuai harapan |
| 3 | Cek status tiket TICKET-0002 dong | `ticket_status` | Tool call | Data tiket Sari Dewi, status Diproses | Sesuai harapan |
| 4 | apa status tiket TICKET-0042 saya? | `ticket_status` | Tool call | Pesan "tidak ditemukan" (memang tidak ada di data) | Sesuai harapan |
| 5 | Berapa gaji karyawan di perusahaan ini? | `faq` | RAG | LLM mengaku tidak punya informasi, tidak mengarang | Sesuai harapan |

**Routing: 5/5 query diarahkan ke komponen yang tepat.**

## Detail Skenario

### 1. Pertanyaan kebijakan (RAG)

```
POST /ask  {"query": "Berapa jatah cuti tahunan karyawan tetap?"}
→ {"status": "success", "intent": "faq",
   "data": "Halo! Karyawan tetap mendapatkan jatah 12 hari cuti tahunan. Jatah ini dapat mulai diambil setelah Anda memiliki masa kerja minimal 3 bulan."}
```

Observasi: query mengandung frasa yang sangat mirip FAQ pertama di knowledge base.
Retrieval langsung kena entri yang tepat; jawaban LLM persis isi FAQ, tidak ditambah-tambah.

### 2. Pertanyaan kebijakan dengan bahasa sendiri (RAG)

```
POST /ask  {"query": "gimana cara reset password VPN saya ya?"}
→ {"status": "success", "intent": "faq",
   "data": "Halo! Anda dapat melakukan reset password VPN secara mandiri melalui portal self-service IT. Jika akun Anda terkunci, silakan hubungi tim IT Support untuk mendapatkan bantuan lebih lanjut."}
```

Observasi: bahasa query kasual ("gimana…saya ya?") berbeda dari pola FAQ
("Bagaimana cara mengreset password VPN perusahaan?"), tetapi semantic search tetap
menemukan entri yang benar — pencarian berbasis makna, bukan kata identik.

### 3. Cek status tiket yang ada di data (tool call)

```
POST /ask  {"query": "Cek status tiket TICKET-0002 dong"}
→ {"status": "success", "intent": "ticket_status",
   "data": "Tiket TICKET-0002 — Permintaan akses Google Analytics
Karyawan: Sari Dewi | Kategori: Access
Status: Diproses (perbaruan terakhir 2026-08-25)"}
```

Observasi: intent terdeteksi dari keberadaan pola `TICKET-\d+`; `extract_ticket_id`
mengekstrak `TICKET-0002` dari kalimat bebas; data diambil dari `mock_tickets.csv`
**tanpa melalui LLM sama sekali** (tidak ada call embedding/generate di log untuk
skenario ini — murni lookup data).

### 4. Cek status tiket yang TIDAK ada di data (tool call)

```
POST /ask  {"query": "apa status tiket TICKET-0042 saya?"}
→ {"status": "success", "intent": "ticket_status",
   "data": "Tiket TICKET-0042 tidak ditemukan di dalam data tiket. Silakan periksa kembali nomor tiket Anda atau hubungi tim IT Helpdesk."}
```

Observasi: `TICKET-0042` (dari studi kasus brief) memang tidak ada di mock data
(hanya `TICKET-0001`–`TICKET-0015`). Fungsi tool mengembalikan pesan informatif
bukan exception — aplikasi tetap `status: success` dengan intent yang benar,
tidak crash.

### 5. Query di luar cakupan knowledge base (RAG + deteksi ketidaktahuan)

```
POST /ask  {"query": "Berapa gaji karyawan di perusahaan ini?"}
→ {"status": "success", "intent": "faq",
   "data": "Mohon maaf, saya belum memiliki informasi mengenai besaran gaji karyawan. Silakan menghubungi tim IT Helpdesk untuk bantuan lebih lanjut terkait pertanyaan tersebut."}
```

Observasi: knowledge base berisi pertanyaan soal slip gaji, bukan besaran gaji —
FAISS tetap mengembalikan 3 entri terdekat (top-k selalu mengembalikan hasil),
namun LLM jujur menyatakan informasi tidak tersedia. Aturan "hanya boleh menjawab
dari Context" di prompt terbukti bekerja; tidak ada pengarangan angka gaji.

## Pengamatan Tambahan: Penanganan Error LLM

Saat pengujian lokal, skenario 5 sempat kali pertama mengembalikan:

```
{"status": "error", "intent": "unknown",
   "data": "Layanan AI sedang tidak dapat memproses permintaan Anda (kesalahan konfigurasi API key atau gangguan dari LLM). Silakan coba lagi nanti."}
```

Penyebabnya bukan bug aplikasi: API Gemini mengembalikan `503 UNAVAILABLE
("This model is currently experiencing high demand")`. Log server memperlihatkan
traceback lengkap ditangkap oleh `try/except` di endpoint `/ask`, sehingga client
menerima response terstruktur dan aplikasi tetap hidup (request berikutnya normal).
Retry beberapa detik kemudian berhasil. Ini membuktikan penanganan error sesuai
brief langkah 7 berfungsi pada kondisi nyata, bukan sekadar teori.

## Verifikasi Environment Variables

| Pemeriksaan | Hasil |
| :---------- | :---- |
| `grep` literal API key di seluruh source `app/` | Tidak ditemukan |
| Isi container (`docker exec … ls /app`) | Tidak ada file `.env` di image |
| `docker logs` | Tidak memuat nilai API key |
| API key dibaca dari | Environment variable `GEMINI_API_KEY` (`--env-file .env`) |
