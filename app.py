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
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    
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
        page_text = reader.pages[-1].extract_text()
        if page_text:
            text = page_text
    else:
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    
    return text


# =========================================================
# 🔧 FUNGSI BARU: Deteksi & Ekstraksi Nama (Individu & Perusahaan)
# =========================================================
def detect_and_extract_nama(text):
    """
    Deteksi apakah PDF SLIK Individu atau Perusahaan, lalu ekstrak nama.
    Mengembalikan (nama, jenis_debitur) dimana jenis_debitur = 'individu' | 'perusahaan'
    """
    header_text = text[:3000].upper()
    has_npwp = 'NPWP' in header_text
    has_nik = bool(re.search(r'\bNIK\s*/', header_text))
    
    is_perusahaan = has_npwp and not has_nik
    
    if is_perusahaan:
        nama = extract_nama_perusahaan(text)
        return nama, 'perusahaan'
    else:
        nama = extract_nama_individu(text)
        return nama, 'individu'


def extract_nama_individu(text):
    """Ekstraksi nama untuk SLIK Individu (logika lama)"""
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
    return nama


def extract_nama_perusahaan(text):
    """
    Ekstraksi nama perusahaan (Badan Usaha) dari teks SLIK.
    
    Strategi:
    1. Cari semua baris yang merupakan nama bank pelapor (pola: "PT ... / DD Bulan YYYY" atau "... Finance / DD Bulan YYYY")
    2. Nama perusahaan biasanya muncul tepat SEBELUM baris nama bank tersebut
    3. Filter: buang baris yang merupakan alamat, kode pos, atau bagian dari "Bentuk BU"
    """
    lines = text.splitlines()
    
    # Pola untuk mendeteksi baris nama bank pelapor
    # Contoh: "PT Bank Central Asia Tbk / 11 Juni 2026"
    #         "PT Mandiri Tunas Finance / 10 Juni 2026"
    #         "PT Astra Sedaya Finance / 11 Juni 2026"
    bank_pattern = re.compile(
        r'^(PT\s+[A-Z][A-Za-z\s\.\,]+(?:Tbk|Finance|Multifinance|Indonesia|BNI|BRI|Mandiri|OCBC|BCA|Panin|Danamon|CIMB|Permata|BTPN|Bukopin|Sinarmas|Niaga|Maybank|UOB|HSBC|Citibank|Standard Chartered|ANZ|DBS|NISP|BII|BTN|BJB|BPD|BPR|BNI|BRI|Bank)\s*/\s*\d{1,2}\s+\w+\s+\d{4})',
        re.IGNORECASE
    )
    
    # Kata kunci yang menandakan baris BUKAN nama (alamat, kode pos, bentuk BU, dll)
    bukan_nama_pattern = re.compile(
        r'(KAB\.?|KOTA|KEC\.?|KEL\.?|DESA|RT\.?\s*\d|RW\.?\s*\d|JL\.?|JALAN|INDONESIA|'
        r'KODE POS|KODEPOS|\d{5}|'
        r'COMMANDITER|PERSEROAN|GO PUBLIC|BENTUK BU|BENTUHBADANUSAHA|'
        r'PELAPOR|TANGGAL UPDATE|NAMA DEBITUR|ALAMAT|KELURAHAN|KECAMATAN|'
        r'NPWP|TEMPAT PENDIRIAN|TANGGAL AKTE|NO/TGL AKTA|PEMERINGKAT|'
        r'BIDANG USAHA|PEMILIK|PENGURUS|OPERATOR|KODE REF|POSISI DATA|'
        r'LJK|PERUNTUKAN|TANGGAL DIBENTUK|HALAMAN|RAHASIA|INFORMASI DEBITUR|'
        r'JAWA BARAT|JAWA TIMUR|JAWA TENGAH|DKI JAKARTA|SUMATERA|BALI|KALIMANTAN|SULAWESI)',
        re.IGNORECASE
    )
    
    # Cari semua indeks baris yang merupakan nama bank pelapor
    bank_indices = []
    for i, line in enumerate(lines):
        if bank_pattern.match(line.strip()):
            bank_indices.append(i)
    
    if not bank_indices:
        # Fallback: cari nama setelah "Nama Debitur"
        nm = re.search(r'Nama Debitur\s*\n([A-Z][A-Z\s\.\,\-\&\/]{3,}?)\s*\n', text)
        if nm:
            return nm.group(1).strip()
        return "(Tidak ditemukan)"
    
    # Untuk setiap bank, lihat baris sebelumnya untuk mencari nama perusahaan
    nama_candidates = []
    for bank_idx in bank_indices:
        # Cek 1-5 baris sebelum bank
        for offset in range(1, 6):
            idx = bank_idx - offset
            if idx < 0:
                continue
            candidate = lines[idx].strip()
            
            # Skip baris kosong
            if not candidate:
                continue
            
            # Skip jika mengandung kata kunci alamat/bukan nama
            if bukan_nama_pattern.search(candidate):
                continue
            
            # Skip jika mengandung angka (kemungkinan kode pos, tanggal, dll)
            if re.search(r'\d', candidate):
                continue
            
            # Skip jika terlalu pendek
            if len(candidate) < 3:
                continue
            
            # Skip jika bukan huruf kapital semua (nama perusahaan biasanya kapital)
            if not candidate.replace(' ', '').replace('-', '').replace('.', '').replace('&', '').replace('/', '').replace('(', '').replace(')', '').isupper():
                continue
            
            # Skip jika mengandung kata "Tbk" atau "Finance" (itu nama bank)
            if re.search(r'\b(Tbk|Finance|Bank|Multifinance)\b', candidate, re.IGNORECASE):
                continue
            
            # Kandidat valid
            nama_candidates.append(candidate)
            break  # Ambil kandidat pertama yang valid untuk bank ini
    
    if not nama_candidates:
        return "(Tidak ditemukan)"
    
    # Pilih nama yang paling sering muncul (karena nama perusahaan muncul berulang di setiap blok pelapor)
    from collections import Counter
    counter = Counter(nama_candidates)
    most_common = counter.most_common(1)[0][0]
    
    return most_common


# =========================================================
# 1️⃣  FUNGSI EKSTRAKSI SLIK
# =========================================================
def extract_slik_data_from_bytes(pdf_bytes, pdf_name):
    text = read_pdf_text(pdf_bytes, last_page_only=False)

    # --- Deteksi & Ekstraksi Nama (Individu/Perusahaan) ---
    nama, jenis_debitur = detect_and_extract_nama(text)

    # --- NIK / NPWP ---
    nik_npwp = "(Tidak ditemukan)"
    if jenis_debitur == 'perusahaan':
        # Cari NPWP (15 digit) atau NPWP format dengan titik/garis
        npwp_match = re.search(r'\b(\d{2}\.?\d{3}\.?\d{3}\.?\d{1}-?\d{3}\.?\d{3})\b', text)
        if npwp_match:
            nik_npwp = npwp_match.group(1)
        else:
            # Fallback: cari 15 digit berurutan
            npwp_match = re.search(r'\b(\d{15})\b', text)
            if npwp_match:
                nik_npwp = npwp_match.group(1)
    else:
        # Cari NIK (16 digit)
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
            "Jenis Debitur": jenis_debitur,
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
    text_all = read_pdf_text(pdf_bytes, last_page_only=False)
    
    is_bca = bool(re.search(r'REKENING GIRO|REKENING TABUNGAN|BCA|Laporan Mutasi Rekening', text_all, re.IGNORECASE))
    is_bri = bool(re.search(r'Statement Date|BRISIM|Opening Balance', text_all, re.IGNORECASE))
    is_panin = bool(re.search(r'Bank Panin Dubai Syariah|Account Statement|PINJAMAN REKENING KORAN', text_all, re.IGNORECASE))

    if is_panin:
        return extract_mutasi_panin(text_all, pdf_name)
    elif is_bca and not is_bri:
        text_last = read_pdf_text(pdf_bytes, last_page_only=True)
        return extract_mutasi_bca(text_all, text_last, pdf_name)
    else:
        return extract_mutasi_bri(text_all, pdf_name)


def extract_mutasi_panin(text, pdf_name):
    """Ekstraksi format Bank Panin Dubai Syariah"""
    nama = "(Tidak ditemukan)"
    nm = re.search(r'Customer\s*:\s*\d+\s+([A-Z][A-Z\s,\.\-]+?)(?:\n|$)', text, re.IGNORECASE)
    if nm:
        nama = nm.group(1).strip()
    else:
        am = re.search(r'Account\s*:\s*\d+\s+([A-Z][A-Z\s,\.\-]+?)(?:\n|$)', text, re.IGNORECASE)
        if am:
            nama = am.group(1).strip()
    
    no_rek = "(Tidak ditemukan)"
    rm = re.search(r'Account\s*:\s*(\d+)\s+', text, re.IGNORECASE)
    if rm:
        no_rek = rm.group(1)
    
    cabang = "(Tidak ditemukan)"
    cm = re.search(r'Account Statement\s+(\d+)\s*-\s*KC\s+([A-Z\s]+)', text, re.IGNORECASE)
    if cm:
        cabang = cm.group(2).strip()
    
    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    
    dates = re.findall(r'(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', text, re.IGNORECASE)
    if dates:
        last_date = dates[-1]
        date_parts = last_date.split()
        if len(date_parts) >= 3:
            bulan_raw = date_parts[1].upper()
            bulan_str = BULAN_TEXT_MAP.get(bulan_raw, bulan_raw.capitalize())
            tahun_str = '20' + date_parts[2]
    
    transactions = []
    lines = text.splitlines()
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        date_match = re.match(r'^(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', line, re.IGNORECASE)
        if date_match:
            book_date = date_match.group(1)
            remaining = line[len(book_date):].strip()
            
            ref_match = re.match(r'^([A-Z0-9\\]+)\s*', remaining)
            ref = ref_match.group(1) if ref_match else ""
            
            desc_part = remaining[len(ref):].strip() if ref else remaining
            
            value_date_match = re.search(r'(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', desc_part, re.IGNORECASE)
            
            value_date = book_date
            desc = desc_part
            
            if value_date_match:
                value_date = value_date_match.group(1)
                desc = desc_part[:value_date_match.start()].strip()
                after_value = desc_part[value_date_match.end():].strip()
            else:
                after_value = ""
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    vd_match = re.search(r'^(\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2})', next_line, re.IGNORECASE)
                    if vd_match:
                        value_date = vd_match.group(1)
                        after_value = next_line[len(value_date):].strip()
                        if len(desc) < 5:
                            desc = desc + " " + next_line[:vd_match.start()].strip()
            
            if not after_value and i + 1 < len(lines):
                next_line = lines[i+1].strip()
                if re.search(r'[\d\.,]+\s+[\d\.,]+', next_line):
                    after_value = next_line
            
            debit = "-"
            credit = "-"
            closing_balance = "-"
            
            numbers = re.findall(r'-?[\d,]+\.\d{2}|-?[\d\.]+,\d{2}', after_value)
            
            parsed_numbers = []
            for num in numbers:
                try:
                    if ',' in num and '.' in num:
                        if num.index(',') < num.index('.'):
                            val = float(num.replace(',', ''))
                        else:
                            val = float(num.replace('.', '').replace(',', '.'))
                    elif ',' in num:
                        val = float(num.replace(',', '.'))
                    elif '.' in num:
                        val = float(num)
                    else:
                        val = float(num)
                    parsed_numbers.append((num, val))
                except:
                    pass
            
            desc_upper = desc.upper()
            
            if len(parsed_numbers) >= 3:
                if parsed_numbers[0][1] < 0:
                    debit = parsed_numbers[0][0]
                    credit = parsed_numbers[1][0] if parsed_numbers[1][1] > 0 else "-"
                    closing_balance = parsed_numbers[2][0]
                elif 'MASUK' in desc_upper or 'KREDIT' in desc_upper:
                    credit = parsed_numbers[0][0]
                    debit = "-"
                    closing_balance = parsed_numbers[1][0] if len(parsed_numbers) > 1 else "-"
                elif 'TAX' in desc_upper or 'PAJAK' in desc_upper:
                    debit = parsed_numbers[0][0]
                    credit = "-"
                    closing_balance = parsed_numbers[1][0] if len(parsed_numbers) > 1 else "-"
                elif 'PROFIT' in desc_upper or 'BAGI HASIL' in desc_upper:
                    credit = parsed_numbers[0][0]
                    debit = "-"
                    closing_balance = parsed_numbers[1][0] if len(parsed_numbers) > 1 else "-"
                else:
                    debit = parsed_numbers[0][0]
                    credit = parsed_numbers[1][0] if len(parsed_numbers) > 1 and parsed_numbers[1][1] > 0 else "-"
                    closing_balance = parsed_numbers[2][0] if len(parsed_numbers) > 2 else "-"
            
            elif len(parsed_numbers) == 2:
                if 'MASUK' in desc_upper or 'KREDIT' in desc_upper:
                    credit = parsed_numbers[0][0]
                    closing_balance = parsed_numbers[1][0]
                elif 'TAX' in desc_upper or 'PAJAK' in desc_upper:
                    debit = parsed_numbers[0][0]
                    closing_balance = parsed_numbers[1][0]
                elif 'PROFIT' in desc_upper or 'BAGI HASIL' in desc_upper:
                    credit = parsed_numbers[0][0]
                    closing_balance = parsed_numbers[1][0]
                else:
                    debit = parsed_numbers[0][0]
                    closing_balance = parsed_numbers[1][0]
            
            elif len(parsed_numbers) == 1:
                if 'MASUK' in desc_upper:
                    credit = parsed_numbers[0][0]
                else:
                    debit = parsed_numbers[0][0]
            
            if debit and debit != "-":
                try:
                    val = float(debit.replace(',', '')) if ',' in debit else float(debit)
                    debit = fmt_rp_id(val)
                except:
                    pass
            
            if credit and credit != "-":
                try:
                    val = float(credit.replace(',', '')) if ',' in credit else float(credit)
                    credit = fmt_rp_id(val)
                except:
                    pass
            
            if closing_balance and closing_balance != "-":
                try:
                    is_negative = False
                    if '-' in closing_balance:
                        is_negative = True
                        closing_balance = closing_balance.replace('-', '')
                    
                    val = float(closing_balance.replace(',', '')) if ',' in closing_balance else float(closing_balance)
                    if is_negative or val < 0:
                        closing_balance = "-" + fmt_rp_id(abs(val))
                    else:
                        closing_balance = fmt_rp_id(val)
                except:
                    pass
            
            if debit != "-" or credit != "-":
                desc = re.sub(r'\\[A-Z]+\s*', ' ', desc)
                desc = re.sub(r'\s+', ' ', desc).strip()
                
                if not desc:
                    if credit != "-":
                        desc = "TRANSFER MASUK"
                    elif debit != "-":
                        desc = "TRANSFER KELUAR"
                    else:
                        desc = "TRANSAKSI"
                
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    if not re.match(r'^\d{2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2}', next_line, re.IGNORECASE):
                        if not re.match(r'^[\d\.,\s-]+$', next_line):
                            if 'Pengirim' in next_line or 'To Acc' in next_line or 'INVOICE' in next_line:
                                desc = desc + " " + next_line[:100]
                
                desc = re.sub(r'\s+', ' ', desc).strip()
                
                transactions.append({
                    "Book Date": book_date,
                    "Value Date": value_date,
                    "Deskripsi": desc[:300],
                    "Debit": debit,
                    "Kredit": credit,
                    "Closing Balance": closing_balance
                })
        
        i += 1
    
    seen = set()
    unique_transactions = []
    for t in transactions:
        key = (t['Value Date'], t['Deskripsi'][:30], t['Debit'], t['Kredit'])
        if key not in seen:
            seen.add(key)
            unique_transactions.append(t)
    transactions = unique_transactions
    
    saldo_awal = 0.0
    sa_match = re.search(r'Balance at Period\s*S\s*tart\s*([\d\.,]+)', text, re.IGNORECASE)
    if sa_match:
        try:
            saldo_awal = parse_rp_id(sa_match.group(1))
        except:
            saldo_awal = 0.0
    
    plafond = 0.0
    pl_match = re.search(r'Plafond\s*:\s*([\d\.,]+)', text, re.IGNORECASE)
    if pl_match:
        try:
            plafond = parse_rp_id(pl_match.group(1))
        except:
            plafond = 0.0
    
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
    
    saldo_akhir = saldo_awal + total_kredit - total_debet
    
    return {
        "Nama": nama,
        "No Rekening": no_rek,
        "Cabang": cabang,
        "Bulan": bulan_str,
        "Tahun": tahun_str,
        "Plafond": fmt_rp_id(plafond) if plafond > 0 else "-",
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
    nama = "(Tidak ditemukan)"
    nm = re.search(r'Statement Date\n:\n[\d/]+\n([A-Z][A-Z\s]+?)\s*\n', text)
    if nm:
        nama = nm.group(1).strip()

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
    """Ekstraksi format BCA (Rekening Giro/Tabungan)"""
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

    cabang = "(Tidak ditemukan)"
    cm = re.search(r'REKENING (?:GIRO|TABUNGAN)\s*\n([^\n]+)', text_all, re.IGNORECASE)
    if cm:
        cabang = cm.group(1).strip()

    no_rek = "(Tidak ditemukan)"
    rm = re.search(r'NO\.?\s*REKENING\s*[:\s]*(\d+)', text_all, re.IGNORECASE)
    if rm:
        no_rek = rm.group(1)

    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    pm = re.search(r'PERIODE\s*[:\s]*([A-Za-z]+)\s+(\d{4})', text_all, re.IGNORECASE)
    if pm:
        bulan_raw = pm.group(1).upper()
        bulan_str = BULAN_TEXT_MAP.get(bulan_raw, pm.group(1).capitalize())
        tahun_str = pm.group(2)

    saldo_awal = total_debet = total_kredit = saldo_akhir = 0.0

    saldo_area_match = re.search(r'SALDO AWAL.*?SALDO AKHIR\s*[:\-]*\s*([\d\.,\-]+)', text_last, re.IGNORECASE | re.DOTALL)
    if saldo_area_match:
        saldo_area = saldo_area_match.group(0)
        numbers = re.findall(r'-?[\d,]+\.\d{2}', saldo_area)
        if len(numbers) >= 4:
            saldo_awal   = parse_rp_us(numbers[0])
            total_kredit = parse_rp_us(numbers[1])
            total_debet  = parse_rp_us(numbers[2])
            saldo_akhir  = parse_rp_us(numbers[3])
        elif len(numbers) == 3:
            total_kredit = parse_rp_us(numbers[0])
            total_debet  = parse_rp_us(numbers[1])
            saldo_akhir  = parse_rp_us(numbers[2])

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
    st.write("Unggah satu atau beberapa file PDF SLIK untuk diekstrak. (Mendukung **SLIK Individu** & **SLIK Perusahaan/Badan Usaha**)")

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

            # Tampilkan info jenis debitur
            if 'Jenis Debitur' in df_all.columns:
                jenis_counts = df_all['Jenis Debitur'].value_counts()
                info_text = " | ".join([f"{k.capitalize()}: {v} record" for k, v in jenis_counts.items()])
                st.info(f"📋 **Jenis Debitur Terdeteksi:** {info_text}")

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
        panin_files = []

        with st.spinner("Memproses file mutasi... ⏳"):
            for uf in uploaded_files:
                try:
                    row = extract_mutasi_from_bytes(uf.read(), uf.name)
                    if row:
                        results.append(row)
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

            st.subheader("📥 Download Rekap Mutasi")
            excel_buf = build_mutasi_excel(df_mutasi)
            st.download_button(
                "⬇️ Unduh Rekap Mutasi (Excel)",
                data=excel_buf,
                file_name=f"Rekap_Mutasi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

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
                    
                    with st.expander("👁️ Preview Detail Transaksi Panin"):
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
                            df_preview_tx = pd.DataFrame(all_tx[:20])
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
