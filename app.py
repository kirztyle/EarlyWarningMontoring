import streamlit as st
import pandas as pd
from PyPDF2 import PdfReader
import re
import os
from datetime import datetime
from io import BytesIO
import warnings
warnings.filterwarnings('ignore')

# =========================================================
# KONSTANTA
# =========================================================
BULAN_MAP = {
    '01': 'Januari', '02': 'Februari', '03': 'Maret',    '04': 'April',
    '05': 'Mei',     '06': 'Juni',     '07': 'Juli',     '08': 'Agustus',
    '09': 'September','10': 'Oktober', '11': 'November', '12': 'Desember'
}

BULAN_TEXT_MAP = {
    'JANUARI': 'Januari', 'FEBRUARI': 'Februari', 'MARET': 'Maret', 'APRIL': 'April',
    'MEI': 'Mei', 'JUNI': 'Juni', 'JULI': 'Juli', 'AGUSTUS': 'Agustus',
    'SEPTEMBER': 'September', 'OKTOBER': 'Oktober', 'NOVEMBER': 'November', 'DESEMBER': 'Desember',
    'JAN': 'Januari', 'FEB': 'Februari', 'MAR': 'Maret', 'APR': 'April',
    'MAY': 'Mei', 'JUN': 'Juni', 'JUL': 'Juli', 'AUG': 'Agustus',
    'SEP': 'September', 'OCT': 'Oktober', 'NOV': 'November', 'DEC': 'Desember'
}

# =========================================================
# HELPER: Baca PDF (support enkripsi AES)
# =========================================================
def read_pdf_text(pdf_bytes, last_page_only=False):
    """
    Membaca teks dari PDF bytes. 
    Menangani PDF yang terenkripsi (termasuk null encryption / AES).
    
    Args:
        pdf_bytes: Bytes dari file PDF
        last_page_only: Jika True, hanya membaca halaman terakhir saja
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    
    # Handle PDF terenkripsi
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise ValueError(
                f"PDF terenkripsi dan tidak bisa dibuka. "
                f"Pastikan PyCryptodome sudah terinstall: `pip install PyCryptodome`. "
                f"Error: {e}"
            )
    
    text = ""
    if last_page_only and len(reader.pages) > 0:
        # Hanya baca halaman terakhir
        page_text = reader.pages[-1].extract_text()
        if page_text:
            text = page_text
    else:
        # Baca semua halaman
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    
    return text


# =========================================================
# 1️⃣  FUNGSI EKSTRAKSI SLIK
# =========================================================
def extract_slik_data_from_bytes(pdf_bytes, pdf_name):
    text = read_pdf_text(pdf_bytes, last_page_only=False)

    # --- Nama ---
    nama = "(Tidak ditemukan)"
    nama_match = re.search(r'([A-Z][A-Z\s]+)\nNIK\s*/\s*\n(\d{16})', text)
    if nama_match:
        nama = nama_match.group(1).strip()
    else:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r'^NIK\s*/', line) and i > 0:
                candidate = lines[i-1].strip()
                if candidate and candidate.isupper() and len(candidate) > 2:
                    nama = candidate
                    break
    if nama == "(Tidak ditemukan)":
        m = re.search(r'\b(SOLEHUDIN|[A-Z]{3,}(?:\s+[A-Z]{2,})+)\b', text)
        if m:
            nama = m.group(1).strip()

    # --- NIK ---
    nik_npwp = "(Tidak ditemukan)"
    nik_match = re.search(r'\b(\d{16})\b', text)
    if nik_match:
        nik_npwp = nik_match.group(1)

    # --- Blok kredit ---
    HEADER_MARKER = "Pelapor\nCabang\nBaki Debet\nTanggal Update"
    positions = [m.start() for m in re.finditer(re.escape(HEADER_MARKER), text)]

    if not positions:
        return pd.DataFrame()

    records = []

    for i, pos in enumerate(positions):
        lookback_start = max(0, pos - 800)
        header_section = text[lookback_start:pos]
        next_pos = positions[i+1] if i + 1 < len(positions) else len(text)
        detail_section = text[pos + len(HEADER_MARKER):next_pos]

        baki_date_match = re.search(
            r'Rp\s*([\d\.,]+,\d{2})\s+(\d{1,2}\s+\w+\s+\d{4})\s*$', header_section)
        baki_debet   = f"Rp {baki_date_match.group(1)}" if baki_date_match else "Rp 0,00"
        tanggal_update = baki_date_match.group(2) if baki_date_match else ""

        pelapor = "(Tidak ditemukan)"
        pm = re.search(
            r'(\d{3,6}\s*-\s*[A-Za-z].+?)\n([A-Za-z].+?)\nRp\s*[\d\.,]+',
            header_section, re.DOTALL)
        if pm:
            line1 = pm.group(1).strip()
            inner = [l.strip() for l in pm.group(2).split('\n') if l.strip()]
            if len(inner) >= 2:
                pelapor = f"{line1} {' '.join(inner[:-1])}".strip()
            elif len(inner) == 1:
                kw = re.search(r'\b(KC|KCP|KPO|PUSAT|CABANG|KANTOR)\b', inner[0], re.I)
                pelapor = f"{line1} {inner[0]}".strip() if not kw and len(inner[0])<=25 else line1
            else:
                pelapor = line1
            pelapor = re.sub(r'\s+', ' ', pelapor)
        else:
            fm = re.search(r'(\d{3,6}\s*-\s*[A-Za-z][^\n]+)', header_section)
            if fm:
                pelapor = fm.group(1).strip()

        kual = re.search(r'Kualitas\s+(\d+)\s*-', header_section)
        kualitas = kual.group(1) if kual else "(Tidak ditemukan)"

        def gf(pattern, src, group=1, default="(Tidak ditemukan)"):
            m = re.search(pattern, src, re.DOTALL | re.IGNORECASE)
            return re.sub(r'\s+', ' ', m.group(group).strip()) if m else default

        jenis_penggunaan            = gf(r'Jenis Penggunaan\s+(.+?)\s+Frekuensi Restrukturisasi', detail_section)
        frekuensi_restrukturisasi   = gf(r'Frekuensi Restrukturisasi\s+(\S+)', detail_section)
        suku_bunga                  = gf(r'Suku Bunga/Imbalan\s+([\d\.,]+\s*%?)', detail_section)
        jumlah_hari_tunggakan       = gf(r'Jumlah Hari Tunggakan\s+(\S+)', detail_section)
        tanggal_akad_awal           = gf(r'Tanggal Akad Awal\s+(\d{1,2}\s+\w+\s+\d{4})', detail_section, default="")
        tanggal_jatuh_tempo         = gf(r'Tanggal Jatuh Tempo\s+(\d{1,2}\s+\w+\s+\d{4})', detail_section, default="")
        plafon_awal                 = gf(r'Plafon Awal\s+(Rp\s*[\d\.,]+,\d{2})', detail_section)
        tanggal_restrukturisasi     = gf(r'Tanggal Restrukturisasi Akhir\s+(\d{1,2}\s+\w+\s+\d{4})', detail_section, default="")

        plafon = "(Tidak ditemukan)"
        plm = re.search(r'Frekuensi Perpanjangan Kredit/\nPembiayaan\s+\d+\s+Plafon\s+(Rp\s*[\d\.,]+,\d{2})', detail_section)
        if not plm:
            plm = re.search(r'\nPlafon\s+(Rp\s*[\d\.,]+,\d{2})\n', detail_section)
        if plm:
            val = plm.group(1).replace('Rp','').replace(' ','').replace('.','').replace(',','.')
            try:
                plafon = f"{float(val):,.2f}".replace(',','X').replace('.',',').replace('X','.')
            except Exception:
                plafon = plm.group(1)

        km = re.search(r'\nKondisi\s+([^\n]+)', detail_section)
        kondisi = km.group(1).strip() if km else "(Tidak ditemukan)"
        tanggal_kondisi = gf(r'Tanggal Kondisi\s+(\d{1,2}\s+\w+\s+\d{4})', detail_section, default="")

        records.append({
            "Nama Sesuai Identitas": nama,
            "NIK/NPWP": nik_npwp,
            "Pelapor": pelapor,
            "Baki Debet": baki_debet,
            "Tanggal Update": tanggal_update,
            "Plafon Awal": plafon_awal,
            "Plafon": plafon,
            "Kualitas": kualitas,
            "Suku Bunga/Imbalan": suku_bunga,
            "Tanggal Akad Awal": tanggal_akad_awal,
            "Tanggal Jatuh Tempo": tanggal_jatuh_tempo,
            "Jumlah Hari Tunggakan": jumlah_hari_tunggakan,
            "Jenis Penggunaan": jenis_penggunaan,
            "Frekuensi Restrukturisasi": frekuensi_restrukturisasi,
            "Tanggal Restrukturisasi Akhir": tanggal_restrukturisasi,
            "Kondisi": kondisi,
            "Tanggal Kondisi": tanggal_kondisi,
            "Timestamp Ekstraksi": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Nama File PDF": pdf_name
        })

    return pd.DataFrame(records)


# =========================================================
# 2️⃣  FUNGSI EKSTRAKSI MUTASI REKENING (MULTI-BANK: BRI, BCA, PANIN)
# =========================================================
def parse_rp_us(s):
    """Parse format US '151,847.00' → float 151847.00"""
    try:
        return float(str(s).replace(',', ''))
    except Exception:
        return 0.0

def parse_rp_id(s):
    """Parse format Indonesia '151.847,00' → float 151847.00"""
    try:
        return float(str(s).replace('.', '').replace(',', '.'))
    except Exception:
        return 0.0

def fmt_rp_id(v):
    """Format float → string Rupiah format Indonesia: 151.847,00"""
    return f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def extract_mutasi_from_bytes(pdf_bytes, pdf_name):
    # Baca semua halaman dulu untuk deteksi bank
    text_all = read_pdf_text(pdf_bytes, last_page_only=False)
    
    # Deteksi bank berdasarkan kata kunci
    is_bca = bool(re.search(r'REKENING GIRO|REKENING TABUNGAN|BCA|Laporan Mutasi Rekening', text_all, re.IGNORECASE))
    is_bri = bool(re.search(r'Statement Date|BRISIM|Opening Balance', text_all, re.IGNORECASE))
    is_panin = bool(re.search(r'Bank Panin Dubai Syariah|Account Statement|PINJAMAN REKENING KORAN', text_all, re.IGNORECASE))

    if is_panin:
        # Untuk Panin, baca semua halaman
        return extract_mutasi_panin(text_all, pdf_name)
    elif is_bca and not is_bri:
        # Untuk BCA, baca hanya halaman terakhir
        text_last = read_pdf_text(pdf_bytes, last_page_only=True)
        return extract_mutasi_bca(text_all, text_last, pdf_name)
    else:
        return extract_mutasi_bri(text_all, pdf_name)


def extract_mutasi_panin(text, pdf_name):
    """
    Ekstraksi format Bank Panin Dubai Syariah
    Dengan kolom: Deskripsi, Tanggal Nilai, Debit, Kredit, Closing Balance
    """
    # --- Nama Nasabah ---
    nama = "(Tidak ditemukan)"
    nm = re.search(r'Customer\s*:\s*\d+\s+([A-Z][A-Z\s,\.\-]+?)(?:\n|$)', text, re.IGNORECASE)
    if nm:
        nama = nm.group(1).strip()
    else:
        am = re.search(r'Account\s*:\s*\d+\s+([A-Z][A-Z\s,\.\-]+?)(?:\n|$)', text, re.IGNORECASE)
        if am:
            nama = am.group(1).strip()
    
    # --- No Rekening ---
    no_rek = "(Tidak ditemukan)"
    rm = re.search(r'Account\s*:\s*(\d+)\s+', text, re.IGNORECASE)
    if rm:
        no_rek = rm.group(1)
    
    # --- Cabang ---
    cabang = "(Tidak ditemukan)"
    cm = re.search(r'Account Statement\s+(\d+)\s*-\s*KC\s+([A-Z\s]+)', text, re.IGNORECASE)
    if cm:
        cabang = cm.group(2).strip()
    
    # --- Periode ---
    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    
    # Cari semua tanggal dalam format DD MMM YY
    dates = re.findall(r'(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', text, re.IGNORECASE)
    if dates:
        last_date = dates[-1]
        date_parts = last_date.split()
        if len(date_parts) >= 3:
            bulan_raw = date_parts[1].upper()
            bulan_str = BULAN_TEXT_MAP.get(bulan_raw, bulan_raw.capitalize())
            tahun_str = '20' + date_parts[2]
    
    # --- Ekstrak Transaksi ---
    transactions = []
    
    # Pattern untuk menangkap transaksi dengan format yang berantakan
    # Contoh: "06 AUG 24 FT2421999HGJ\BN KTRANSFER MASUK BIFAST06 AUG 24  1,000,000.00 1,000,000.00"
    
    # Cari semua transaksi dengan pola yang lebih baik
    # Pola: Tanggal Buku + Referensi + Deskripsi + Tanggal Nilai + Angka
    lines = text.splitlines()
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Cari baris yang dimulai dengan tanggal (DD MMM YY)
        date_match = re.match(r'^(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', line, re.IGNORECASE)
        if date_match:
            book_date = date_match.group(1)
            
            # Ambil sisa baris setelah tanggal
            remaining = line[len(book_date):].strip()
            
            # Cari referensi (biasanya diawali FT atau kode lain)
            ref_match = re.match(r'^([A-Z0-9\\]+)\s*', remaining)
            ref = ref_match.group(1) if ref_match else ""
            
            # Sisa setelah referensi adalah deskripsi + tanggal nilai + angka
            desc_part = remaining[len(ref):].strip() if ref else remaining
            
            # Cari tanggal nilai di dalam desc_part
            value_date_match = re.search(r'(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', desc_part, re.IGNORECASE)
            
            value_date = ""
            desc = desc_part
            
            if value_date_match:
                value_date = value_date_match.group(1)
                # Ambil deskripsi sebelum tanggal nilai
                desc = desc_part[:value_date_match.start()].strip()
                # Ambil angka setelah tanggal nilai
                after_value = desc_part[value_date_match.end():].strip()
            else:
                # Jika tidak ada tanggal nilai di baris yang sama, cek baris berikutnya
                after_value = ""
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    vd_match = re.search(r'^(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', next_line, re.IGNORECASE)
                    if vd_match:
                        value_date = vd_match.group(1)
                        after_value = next_line[len(value_date):].strip()
                        # Gabungkan deskripsi dengan baris berikutnya jika perlu
                        if len(desc) < 10:
                            desc = desc + " " + next_line[:vd_match.start()].strip()
            
            # Ekstrak angka dari after_value
            debit = "-"
            credit = "-"
            closing_balance = "-"
            
            # Cari semua angka dengan format Indonesia (1.000.000,00) atau US (1,000,000.00)
            numbers = re.findall(r'[\d\.,]+', after_value)
            
            # Filter angka yang valid (bukan tanggal)
            valid_numbers = []
            for num in numbers:
                # Cek apakah ini angka (bukan tanggal)
                if not re.match(r'^\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2}$', num, re.IGNORECASE):
                    try:
                        # Coba parse sebagai angka
                        if '.' in num and ',' in num:
                            # Format Indonesia: 1.000.000,00
                            val = parse_rp_id(num)
                        elif ',' in num and '.' in num:
                            # Format US: 1,000,000.00
                            val = parse_rp_us(num)
                        elif '.' in num:
                            # Mungkin format Indonesia tanpa koma ribuan
                            val = float(num.replace('.', ''))
                        elif ',' in num:
                            val = float(num.replace(',', '.'))
                        else:
                            val = float(num)
                        valid_numbers.append((num, val))
                    except:
                        pass
            
            # Tentukan debit, kredit, dan closing balance
            # Berdasarkan konteks deskripsi
            desc_upper = desc.upper()
            
            if 'TRANSFER MASUK' in desc_upper or 'MASUK' in desc_upper:
                # Transaksi masuk = kredit
                if len(valid_numbers) >= 2:
                    credit = valid_numbers[0][0]
                    closing_balance = valid_numbers[1][0] if len(valid_numbers) > 1 else valid_numbers[0][0]
                elif len(valid_numbers) >= 1:
                    credit = valid_numbers[0][0]
                    closing_balance = valid_numbers[0][0]
            elif 'TAX' in desc_upper or 'PAJAK' in desc_upper:
                # Transaksi pajak = debit
                if len(valid_numbers) >= 2:
                    debit = valid_numbers[0][0]
                    closing_balance = valid_numbers[1][0] if len(valid_numbers) > 1 else "-"
                elif len(valid_numbers) >= 1:
                    debit = valid_numbers[0][0]
            elif 'PROFIT' in desc_upper or 'BAGI HASIL' in desc_upper:
                # Profit = kredit
                if len(valid_numbers) >= 2:
                    credit = valid_numbers[0][0]
                    closing_balance = valid_numbers[1][0] if len(valid_numbers) > 1 else "-"
                elif len(valid_numbers) >= 1:
                    credit = valid_numbers[0][0]
            elif 'TRANSFER' in desc_upper or 'INVOICE' in desc_upper:
                # Transfer keluar = debit
                if len(valid_numbers) >= 3:
                    debit = valid_numbers[0][0]
                    # Coba tentukan mana kredit dan closing
                    if len(valid_numbers) >= 3:
                        # Jika ada 3 angka: debit, ?, closing
                        # Cek apakah angka kedua adalah kredit (biasanya 0 atau -)
                        if valid_numbers[1][1] == 0:
                            credit = "-"
                            closing_balance = valid_numbers[2][0]
                        else:
                            # Mungkin format: debit, credit, closing
                            credit = valid_numbers[1][0] if len(valid_numbers) > 1 else "-"
                            closing_balance = valid_numbers[2][0] if len(valid_numbers) > 2 else "-"
                    elif len(valid_numbers) >= 2:
                        debit = valid_numbers[0][0]
                        closing_balance = valid_numbers[1][0] if len(valid_numbers) > 1 else "-"
                elif len(valid_numbers) >= 2:
                    debit = valid_numbers[0][0]
                    closing_balance = valid_numbers[1][0]
                elif len(valid_numbers) >= 1:
                    debit = valid_numbers[0][0]
            else:
                # Default: coba tentukan berdasarkan posisi
                if len(valid_numbers) >= 3:
                    # Coba deteksi: jika angka pertama lebih kecil dari angka kedua, mungkin debit, kredit, closing
                    if valid_numbers[0][1] < valid_numbers[1][1]:
                        debit = valid_numbers[0][0]
                        credit = valid_numbers[1][0]
                        closing_balance = valid_numbers[2][0]
                    else:
                        debit = valid_numbers[0][0]
                        closing_balance = valid_numbers[1][0]
                elif len(valid_numbers) >= 2:
                    debit = valid_numbers[0][0]
                    closing_balance = valid_numbers[1][0]
                elif len(valid_numbers) >= 1:
                    debit = valid_numbers[0][0]
            
            # Bersihkan deskripsi dari kode yang tidak perlu
            desc = re.sub(r'\\[A-Z]+\s*', ' ', desc)  # Hapus \BNK dll
            desc = re.sub(r'\s+', ' ', desc).strip()
            
            # Format nilai dengan benar
            if debit and debit != "-":
                try:
                    # Coba parse sesuai format
                    if '.' in debit and ',' in debit:
                        val = parse_rp_id(debit)
                    elif ',' in debit:
                        val = float(debit.replace(',', ''))
                    else:
                        val = float(debit)
                    debit = fmt_rp_id(val)
                except:
                    pass
            
            if credit and credit != "-":
                try:
                    if '.' in credit and ',' in credit:
                        val = parse_rp_id(credit)
                    elif ',' in credit:
                        val = float(credit.replace(',', ''))
                    else:
                        val = float(credit)
                    credit = fmt_rp_id(val)
                except:
                    pass
            
            if closing_balance and closing_balance != "-":
                try:
                    if '.' in closing_balance and ',' in closing_balance:
                        val = parse_rp_id(closing_balance)
                    elif ',' in closing_balance:
                        val = float(closing_balance.replace(',', ''))
                    else:
                        val = float(closing_balance)
                    # Tentukan apakah negatif
                    if ' -' in after_value or '- ' in after_value or val < 0:
                        closing_balance = "-" + fmt_rp_id(abs(val))
                    else:
                        closing_balance = fmt_rp_id(val)
                except:
                    pass
            
            # Hanya tambahkan jika ada transaksi yang valid
            if debit != "-" or credit != "-":
                transactions.append({
                    "Book Date": book_date,
                    "Value Date": value_date if value_date else book_date,
                    "Deskripsi": desc[:300] if desc else f"Transaksi {book_date}",
                    "Debit": debit,
                    "Kredit": credit,
                    "Closing Balance": closing_balance
                })
        
        i += 1
    
    # --- Hapus transaksi duplikat berdasarkan deskripsi dan tanggal ---
    seen = set()
    unique_transactions = []
    for t in transactions:
        key = (t['Value Date'], t['Deskripsi'][:50], t['Debit'], t['Kredit'])
        if key not in seen:
            seen.add(key)
            unique_transactions.append(t)
    transactions = unique_transactions
    
    # --- Ambil Saldo Awal ---
    saldo_awal = 0.0
    sa_match = re.search(r'Balance at Period\s*S\s*tart\s*([\d\.,]+)', text, re.IGNORECASE)
    if sa_match:
        saldo_awal = parse_rp_id(sa_match.group(1))
    
    # --- Ambil Plafond ---
    plafond = 0.0
    pl_match = re.search(r'Plafond\s*:\s*([\d\.,]+)', text, re.IGNORECASE)
    if pl_match:
        plafond = parse_rp_id(pl_match.group(1))
    
    # --- Hitung total debit dan kredit ---
    total_debet = 0.0
    total_kredit = 0.0
    
    for t in transactions:
        if t['Debit'] != '-':
            try:
                total_debet += parse_rp_id(t['Debit'])
            except:
                pass
        if t['Kredit'] != '-':
            try:
                total_kredit += parse_rp_id(t['Kredit'])
            except:
                pass
    
    # Saldo akhir = saldo awal + total_kredit - total_debet
    saldo_akhir = saldo_awal + total_kredit - total_debet
    
    return {
        "Nama": nama,
        "No Rekening": no_rek,
        "Cabang": cabang,
        "Bulan": bulan_str,
        "Tahun": tahun_str,
        "Plafond": fmt_rp_id(plafond),
        "Saldo Awal": fmt_rp_id(saldo_awal),
        "Total Transaksi Debet": fmt_rp_id(total_debet),
        "Total Transaksi Kredit": fmt_rp_id(total_kredit),
        "Saldo Akhir": fmt_rp_id(saldo_akhir),
        "_saldo_awal_num": saldo_awal,
        "_total_debet_num": total_debet,
        "_total_kredit_num": total_kredit,
        "_saldo_akhir_num": saldo_akhir,
        "_transactions": transactions,
        "Nama File PDF": pdf_name,
    }


def extract_mutasi_bri(text, pdf_name):
    """Ekstraksi format BRI (BRISIM)"""
    # --- Nama nasabah ---
    nama = "(Tidak ditemukan)"
    nm = re.search(r'Statement Date\n:\n[\d/]+\n([A-Z][A-Z\s]+?)\s*\n', text)
    if nm:
        nama = nm.group(1).strip()

    # --- Periode transaksi ---
    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    pm = re.search(
        r'Periode Transaksi\s*\nTransaction Period\s*\n:\s*\n(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})',
        text
    )
    if pm:
        start = pm.group(1)
        parts = start.split('/')
        bulan_str = BULAN_MAP.get(parts[1], parts[1])
        tahun_str = '20' + parts[2]

    # --- Saldo & transaksi ---
    saldo_awal = total_debet = total_kredit = saldo_akhir = 0.0

    sm = re.search(
        r'Saldo Awal\nOpening Balance\nTotal Transaksi Debet\nTotal Debit Transaction\n'
        r'Total Transaksi Kredit\nTotal Credit Transaction\nSaldo Akhir\nClosing Balance\n'
        r'([\d,\.]+)\n([\d,\.]+)\n([\d,\.]+)\n([\d,\.]+)',
        text
    )
    if sm:
        saldo_awal   = parse_rp_us(sm.group(1))
        total_debet  = parse_rp_us(sm.group(2))
        total_kredit = parse_rp_us(sm.group(3))
        saldo_akhir  = parse_rp_us(sm.group(4))

    return {
        "Nama": nama,
        "No Rekening": "(Tidak ditemukan)",
        "Cabang": "(Tidak ditemukan)",
        "Bulan": bulan_str,
        "Tahun": tahun_str,
        "Plafond": "-",
        "Saldo Awal": fmt_rp_id(saldo_awal),
        "Total Transaksi Debet": fmt_rp_id(total_debet),
        "Total Transaksi Kredit": fmt_rp_id(total_kredit),
        "Saldo Akhir": fmt_rp_id(saldo_akhir),
        "_saldo_awal_num": saldo_awal,
        "_total_debet_num": total_debet,
        "_total_kredit_num": total_kredit,
        "_saldo_akhir_num": saldo_akhir,
        "_transactions": [],
        "Nama File PDF": pdf_name,
    }


def extract_mutasi_bca(text_all, text_last, pdf_name):
    """
    Ekstraksi format BCA (Rekening Giro/Tabungan)
    
    Args:
        text_all: Teks dari semua halaman (untuk nama, cabang, periode)
        text_last: Teks dari halaman terakhir saja (untuk saldo & mutasi)
        pdf_name: Nama file PDF
    """
    # --- Nama nasabah (dari semua halaman) ---
    nama = "(Tidak ditemukan)"
    nm = re.search(r'REKENING (?:GIRO|TABUNGAN)\s*\n[^\n]+\n([A-Z][A-Z\s\.,\-]+?)\s*\n(?:JL|JALAN|KP|KEL|KEC|KOTA|DESA|RT|RW|BLOK|NO)', text_all, re.IGNORECASE)
    if nm:
        nama = nm.group(1).strip()
    else:
        lines = text_all.splitlines()
        for i, line in enumerate(lines):
            if re.match(r'^REKENING (?:GIRO|TABUNGAN)', line.strip(), re.IGNORECASE):
                if i + 2 < len(lines):
                    candidate = lines[i+2].strip()
                    if candidate and candidate.isupper() and len(candidate) > 3 and not re.match(r'^(JL|JALAN|KP|KEL|NO\.|HALAMAN)', candidate):
                        nama = candidate
                        break

    # --- Cabang (dari semua halaman) ---
    cabang = "(Tidak ditemukan)"
    cm = re.search(r'REKENING (?:GIRO|TABUNGAN)\s*\n([^\n]+)', text_all, re.IGNORECASE)
    if cm:
        cabang = cm.group(1).strip()

    # --- No Rekening (dari semua halaman) ---
    no_rek = "(Tidak ditemukan)"
    rm = re.search(r'NO\.?\s*REKENING\s*[:\s]*(\d+)', text_all, re.IGNORECASE)
    if rm:
        no_rek = rm.group(1)

    # --- Periode (dari semua halaman) ---
    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    pm = re.search(r'PERIODE\s*[:\s]*([A-Za-z]+)\s+(\d{4})', text_all, re.IGNORECASE)
    if pm:
        bulan_raw = pm.group(1).upper()
        bulan_str = BULAN_TEXT_MAP.get(bulan_raw, pm.group(1).capitalize())
        tahun_str = pm.group(2)

    # --- Saldo & Mutasi (HANYA dari halaman terakhir) ---
    saldo_awal = total_debet = total_kredit = saldo_akhir = 0.0

    # Cari area SALDO AWAL sampai SALDO AKHIR di halaman terakhir
    saldo_area_match = re.search(r'SALDO AWAL.*?SALDO AKHIR\s*[:\-]*\s*([\d\.,\-]+)', text_last, re.IGNORECASE | re.DOTALL)
    if saldo_area_match:
        saldo_area = saldo_area_match.group(0)
        # Ekstrak semua angka dengan format US (dengan koma ribuan dan titik desimal)
        numbers = re.findall(r'-?[\d,]+\.\d{2}', saldo_area)
        if len(numbers) >= 4:
            saldo_awal   = parse_rp_us(numbers[0])
            total_kredit = parse_rp_us(numbers[1])  # Mutasi CR
            total_debet  = parse_rp_us(numbers[2])  # Mutasi DB
            saldo_akhir  = parse_rp_us(numbers[3])
        elif len(numbers) == 3:
            # Kadang saldo awal tidak ikut tertangkap
            total_kredit = parse_rp_us(numbers[0])
            total_debet  = parse_rp_us(numbers[1])
            saldo_akhir  = parse_rp_us(numbers[2])

    # Fallback: cari per-label jika cara di atas gagal
    if saldo_awal == 0 and total_debet == 0:
        sa = re.search(r'SALDO AWAL\s*[:\s]*(-?[\d,]+\.\d{2})', text_last, re.IGNORECASE)
        mc = re.search(r'MUTASI CR\s*[:\s]*(-?[\d,]+\.\d{2})', text_last, re.IGNORECASE)
        md = re.search(r'MUTASI DB\s*[:\s]*(-?[\d,]+\.\d{2})', text_last, re.IGNORECASE)
        sa2 = re.search(r'SALDO AKHIR\s*[:\s]*(-?[\d,]+\.\d{2})', text_last, re.IGNORECASE)
        if sa: saldo_awal = parse_rp_us(sa.group(1))
        if mc: total_kredit = parse_rp_us(mc.group(1))
        if md: total_debet = parse_rp_us(md.group(1))
        if sa2: saldo_akhir = parse_rp_us(sa2.group(1))

    return {
        "Nama": nama,
        "No Rekening": no_rek,
        "Cabang": cabang,
        "Bulan": bulan_str,
        "Tahun": tahun_str,
        "Plafond": "-",
        "Saldo Awal": fmt_rp_id(saldo_awal),
        "Total Transaksi Debet": fmt_rp_id(total_debet),
        "Total Transaksi Kredit": fmt_rp_id(total_kredit),
        "Saldo Akhir": fmt_rp_id(saldo_akhir),
        "_saldo_awal_num": saldo_awal,
        "_total_debet_num": total_debet,
        "_total_kredit_num": total_kredit,
        "_saldo_akhir_num": saldo_akhir,
        "_transactions": [],
        "Nama File PDF": pdf_name,
    }


# =========================================================
# 3️⃣  FUNGSI FILTER SLIK → KEMBALIKAN BYTESIO
# =========================================================
def build_filtered_slik_excel(df: pd.DataFrame, filename: str) -> tuple[BytesIO, str]:
    df_processed = df.copy()
    for col in ['Jenis Penggunaan', 'Kondisi', 'Nama Sesuai Identitas']:
        df_processed[col] = df_processed[col].astype(str).str.strip()

    filtered_df = df_processed[
        df_processed['Jenis Penggunaan'].str.contains('Modal Kerja', case=False, na=False) &
        df_processed['Kondisi'].str.contains('Fasilitas', case=False, na=False)
    ].copy()

    if filtered_df.empty:
        return None, "Tidak ada data yang memenuhi kriteria filter"

    def conv_rp(s):
        try:
            return float(str(s).replace('Rp','').replace(' ','').replace('.','').replace(',','.'))
        except Exception:
            return 0.0

    filtered_df['Baki Debet Numeric'] = filtered_df['Baki Debet'].apply(conv_rp)

    grouped_data = []
    for nama, group in filtered_df.groupby('Nama Sesuai Identitas'):
        total = group['Baki Debet Numeric'].sum()
        total_fmt = f"Rp {total:,.2f}".replace(',','X').replace('.',',').replace('X','.')
        sample = group.iloc[0]
        grouped_data.append({
            "Nama Sesuai Identitas": nama,
            "Total Baki Debet": total_fmt,
            "Jumlah Fasilitas": len(group),
            "Pelapor": ", ".join(group['Pelapor'].unique()[:3]),
            "Jenis Penggunaan": sample['Jenis Penggunaan'],
            "Kondisi": sample['Kondisi'],
            "Kualitas": sample['Kualitas'],
            "Rata-rata Kualitas": group['Kualitas'].apply(
                lambda x: float(x) if str(x).isdigit() else 0).mean(),
            "Jumlah Record": len(group),
        })

    result_df = pd.DataFrame(grouped_data)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        filtered_df.to_excel(writer, sheet_name='Data Terfilter', index=False)
        result_df.to_excel(writer, sheet_name='Ringkasan per Nama', index=False)
        df_processed.to_excel(writer, sheet_name='Data Original', index=False)
    
    buf.seek(0)
    msg = f"Berhasil memproses {len(filtered_df)} record dari {len(df)} total record"
    return buf, msg


# =========================================================
# 4️⃣  HELPER: buat Excel mutasi dengan baris TOTAL
# =========================================================
def build_mutasi_excel(df_mutasi: pd.DataFrame) -> BytesIO:
    display_cols = [
        "Nama", "No Rekening", "Cabang", "Bulan", "Tahun", "Plafond",
        "Saldo Awal", "Total Transaksi Debet", "Total Transaksi Kredit", "Saldo Akhir",
        "Nama File PDF",
    ]
    df_show = df_mutasi[display_cols].copy()

    total_debet  = df_mutasi["_total_debet_num"].sum()
    total_kredit = df_mutasi["_total_kredit_num"].sum()
    total_saldo_akhir = df_mutasi["_saldo_akhir_num"].sum()
    total_saldo_awal = df_mutasi["_saldo_awal_num"].sum()

    total_row = {
        "Nama": "TOTAL",
        "No Rekening": "",
        "Cabang": "",
        "Bulan": "",
        "Tahun": "",
        "Plafond": "",
        "Saldo Awal": fmt_rp_id(total_saldo_awal),
        "Total Transaksi Debet": fmt_rp_id(total_debet),
        "Total Transaksi Kredit": fmt_rp_id(total_kredit),
        "Saldo Akhir": fmt_rp_id(total_saldo_akhir),
        "Nama File PDF": "",
    }
    df_total = pd.concat([df_show, pd.DataFrame([total_row])], ignore_index=True)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_total.to_excel(writer, index=False, sheet_name='Rekap Mutasi')
        
        # Format angka
        ws = writer.sheets['Rekap Mutasi']
        for row in ws.iter_rows(min_row=2, min_col=6, max_col=10):
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    try:
                        num_val = float(cell.value.replace('.', '').replace(',', '.'))
                        cell.value = num_val
                        cell.number_format = '#,##0.00'
                    except ValueError:
                        pass
        
        # Auto width
        for col in ws.columns:
            max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    buf.seek(0)
    return buf


# =========================================================
# 5️⃣  FUNGSI BUAT EXCEL DETAIL TRANSAKSI PANIN
# =========================================================
def build_panin_detail_excel(df_mutasi: pd.DataFrame) -> BytesIO:
    """Buat Excel detail transaksi untuk Bank Panin"""
    all_transactions = []
    
    for _, row in df_mutasi.iterrows():
        if '_transactions' in row and row['_transactions']:
            for t in row['_transactions']:
                all_transactions.append({
                    "Nama": row['Nama'],
                    "No Rekening": row['No Rekening'],
                    "Cabang": row['Cabang'],
                    "Book Date": t.get('Book Date', ''),
                    "Value Date": t.get('Value Date', ''),
                    "Deskripsi": t.get('Deskripsi', ''),
                    "Debit": t.get('Debit', '-'),
                    "Kredit": t.get('Kredit', '-'),
                    "Closing Balance": t.get('Closing Balance', '-'),
                    "Nama File PDF": row['Nama File PDF'],
                })
    
    if not all_transactions:
        return None
    
    df_detail = pd.DataFrame(all_transactions)
    
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_detail.to_excel(writer, index=False, sheet_name='Detail Transaksi')
        
        # Auto width
        ws = writer.sheets['Detail Transaksi']
        for col in ws.columns:
            max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
    
    buf.seek(0)
    return buf


# =========================================================
# 6️⃣  STREAMLIT UI
# =========================================================
st.set_page_config(page_title="SLIK & Mutasi Extractor", page_icon="📄", layout="wide")
st.title("📄 SLIK & Mutasi Rekening Extractor")

# ---------- Pilihan Mode ----------
mode = st.radio(
    "Pilih jenis dokumen yang akan diproses:",
    ["📊 Rekap SLIK", "🏦 Rekap Mutasi Rekening"],
    horizontal=True,
)

st.markdown("---")

# ===========================================================
# MODE A : REKAP SLIK
# ===========================================================
if mode == "📊 Rekap SLIK":
    st.subheader("📊 Rekap SLIK")
    st.write("Unggah satu atau beberapa file PDF SLIK untuk diekstrak.")

    uploaded_files = st.file_uploader(
        "Tarik & lepaskan file PDF SLIK di sini",
        type=["pdf"],
        accept_multiple_files=True,
        key="slik_uploader",
    )

    if uploaded_files:
        all_data = []
        errors = []
        with st.spinner("Memproses file SLIK... ⏳"):
            for uf in uploaded_files:
                try:
                    df = extract_slik_data_from_bytes(uf.read(), uf.name)
                    if not df.empty:
                        all_data.append(df)
                except Exception as e:
                    errors.append(f"{uf.name}: {e}")

        if errors:
            for err in errors:
                st.error(f"⚠ {err}")

        if all_data:
            df_all = pd.concat(all_data, ignore_index=True)
            st.success(f"✅ Berhasil memproses {len(uploaded_files)} file PDF!")

            with st.expander("👁️ Preview Data", expanded=True):
                st.dataframe(df_all, use_container_width=True)

            st.subheader("📥 Download Hasil Filtered SLIK")
            st.info("""
            **Filter:** Jenis Penggunaan = "Modal Kerja" **&** Kondisi = "Fasilitas"  
            File berisi 3 sheet: Data Terfilter | Ringkasan per Nama | Data Original
            """)

            excel_buf, filter_msg = build_filtered_slik_excel(df_all, "SLIK_Filtered")
            
            if excel_buf:
                st.success(f"✅ {filter_msg}")
                
                mask = (
                    df_all['Jenis Penggunaan'].str.contains('Modal Kerja', case=False, na=False) &
                    df_all['Kondisi'].str.contains('Fasilitas', case=False, na=False)
                )
                with st.expander("👁️ Preview Data Terfilter"):
                    st.dataframe(df_all[mask], use_container_width=True)

                st.download_button(
                    "⬇️ Unduh SLIK Filtered (Excel)",
                    data=excel_buf,
                    file_name=f"SLIK_Filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.warning(f"⚠ {filter_msg}")

            st.subheader("📥 Download Hasil Ekstraksi Lengkap")
            buf = BytesIO()
            df_all.to_excel(buf, index=False)
            buf.seek(0)
            st.download_button(
                "⬇️ Unduh Excel Lengkap",
                data=buf,
                file_name=f"SLIK_Extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            with st.expander("📈 Statistik Data"):
                c1, c2, c3 = st.columns(3)
                mask_mk = df_all['Jenis Penggunaan'].str.contains('Modal Kerja', case=False, na=False)
                mask_fa = df_all['Kondisi'].str.contains('Fasilitas', case=False, na=False)
                c1.metric("Total Record", len(df_all))
                c1.metric("Nama Unik", df_all['Nama Sesuai Identitas'].nunique())
                c2.metric("Modal Kerja", mask_mk.sum())
                c2.metric("Kondisi Fasilitas", mask_fa.sum())
                c3.metric("Modal Kerja + Fasilitas", (mask_mk & mask_fa).sum())
        elif not errors:
            st.warning("⚠ Tidak ada data yang berhasil diekstrak.")

# ===========================================================
# MODE B : REKAP MUTASI REKENING
# ===========================================================
else:
    st.subheader("🏦 Rekap Mutasi Rekening")
    st.write("Unggah satu atau beberapa file PDF mutasi rekening (mendukung format **BCA**, **BRI**, & **Bank Panin Dubai Syariah**).")
    
    st.info("💡 **Catatan:** Untuk PDF e-statement BCA yang terenkripsi, pastikan library **PyCryptodome** sudah terinstall (`pip install PyCryptodome`).")

    uploaded_files = st.file_uploader(
        "Tarik & lepaskan file PDF Mutasi Rekening di sini",
        type=["pdf"],
        accept_multiple_files=True,
        key="mutasi_uploader",
    )

    if uploaded_files:
        results = []
        errors  = []
        panin_files = []  # Untuk menyimpan file Panin yang berhasil diproses

        with st.spinner("Memproses file mutasi... ⏳"):
            for uf in uploaded_files:
                try:
                    row = extract_mutasi_from_bytes(uf.read(), uf.name)
                    if row:
                        results.append(row)
                        # Cek apakah ini file Panin (ada transaksi detail)
                        if row.get('_transactions'):
                            panin_files.append(row)
                except Exception as e:
                    errors.append(f"{uf.name}: {e}")

        if errors:
            for err in errors:
                st.error(f"⚠ {err}")

        if results:
            df_mutasi = pd.DataFrame(results)
            st.success(f"✅ Berhasil memproses {len(results)} file PDF!")

            # Tampilkan informasi bank yang terdeteksi
            bank_counts = {}
            for r in results:
                if r.get('_transactions'):
                    bank_counts['Panin'] = bank_counts.get('Panin', 0) + 1
                elif r.get('Cabang') != "(Tidak ditemukan)":
                    if 'BCA' in r.get('Cabang', '').upper():
                        bank_counts['BCA'] = bank_counts.get('BCA', 0) + 1
                    else:
                        bank_counts['BRI'] = bank_counts.get('BRI', 0) + 1
                else:
                    bank_counts['BRI'] = bank_counts.get('BRI', 0) + 1
            
            if bank_counts:
                st.write("**Bank terdeteksi:** " + ", ".join([f"{k}: {v} file" for k, v in bank_counts.items()]))

            display_cols = [
                "Nama", "No Rekening", "Cabang", "Bulan", "Tahun", "Plafond",
                "Saldo Awal", "Total Transaksi Debet", "Total Transaksi Kredit", "Saldo Akhir",
                "Nama File PDF",
            ]

            total_debet  = df_mutasi["_total_debet_num"].sum()
            total_kredit = df_mutasi["_total_kredit_num"].sum()
            total_saldo_akhir = df_mutasi["_saldo_akhir_num"].sum()
            total_saldo_awal = df_mutasi["_saldo_awal_num"].sum()

            total_row = {
                "Nama": "➕ TOTAL",
                "No Rekening": "",
                "Cabang": "",
                "Bulan": "",
                "Tahun": "",
                "Plafond": "",
                "Saldo Awal": fmt_rp_id(total_saldo_awal),
                "Total Transaksi Debet": fmt_rp_id(total_debet),
                "Total Transaksi Kredit": fmt_rp_id(total_kredit),
                "Saldo Akhir": fmt_rp_id(total_saldo_akhir),
                "Nama File PDF": "",
            }

            df_preview = pd.concat(
                [df_mutasi[display_cols], pd.DataFrame([total_row])],
                ignore_index=True
            )

            with st.expander("👁️ Preview Rekap Mutasi", expanded=True):
                def highlight_total(row):
                    if str(row["Nama"]).startswith("➕"):
                        return ['background-color: #fff3cd; font-weight: bold'] * len(row)
                    return [''] * len(row)
                st.dataframe(
                    df_preview.style.apply(highlight_total, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("File Diproses", len(results))
            c2.metric("Total Debet",   f"Rp {total_debet:,.0f}")
            c3.metric("Total Kredit",  f"Rp {total_kredit:,.0f}")
            c4.metric("Total Saldo Akhir", f"Rp {total_saldo_akhir:,.0f}")

            # Download Rekap Mutasi
            st.subheader("📥 Download Rekap Mutasi")
            excel_buf = build_mutasi_excel(df_mutasi)
            st.download_button(
                "⬇️ Unduh Rekap Mutasi (Excel)",
                data=excel_buf,
                file_name=f"Rekap_Mutasi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Jika ada file Panin, tampilkan opsi download detail transaksi
            if panin_files:
                st.subheader("📥 Download Detail Transaksi (Bank Panin)")
                st.info("💡 File ini berisi detail setiap transaksi dengan kolom: Deskripsi, Tanggal Nilai, Debit, Kredit, Closing Balance")
                
                detail_buf = build_panin_detail_excel(df_mutasi)
                if detail_buf:
                    st.download_button(
                        "⬇️ Unduh Detail Transaksi Panin (Excel)",
                        data=detail_buf,
                        file_name=f"Panin_Detail_Transaksi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    
                    # Preview detail transaksi
                    with st.expander("👁️ Preview Detail Transaksi Panin"):
                        # Ambil semua transaksi untuk preview
                        all_tx = []
                        for r in panin_files:
                            for t in r.get('_transactions', []):
                                all_tx.append({
                                    "Nama": r['Nama'][:30] + "...",
                                    "Deskripsi": t.get('Deskripsi', '')[:50] + "...",
                                    "Value Date": t.get('Value Date', ''),
                                    "Debit": t.get('Debit', '-'),
                                    "Kredit": t.get('Kredit', '-'),
                                    "Closing Balance": t.get('Closing Balance', '-'),
                                })
                        if all_tx:
                            df_preview_tx = pd.DataFrame(all_tx[:20])  # Tampilkan 20 transaksi pertama
                            st.dataframe(df_preview_tx, use_container_width=True, hide_index=True)
                            if len(all_tx) > 20:
                                st.caption(f"*Menampilkan 20 dari {len(all_tx)} transaksi*")

        elif not errors:
            st.warning("⚠ Tidak ada data mutasi yang berhasil diekstrak dari PDF yang diunggah.")
    else:
        st.info("📎 Silakan unggah satu atau beberapa file PDF Mutasi Rekening.")

# =========================================================
# Footer
# =========================================================
st.markdown("---")
st.caption(
    f"© {datetime.now().year} SLIK & Mutasi Extractor | "
    f"Terakhir diperbarui: {datetime.now().strftime('%d %B %Y %H:%M:%S')}"
)
