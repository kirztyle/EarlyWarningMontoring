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

# =========================================================
# 1️⃣  FUNGSI EKSTRAKSI SLIK
# =========================================================
def extract_slik_data_from_bytes(pdf_bytes, pdf_name):
    reader = PdfReader(BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"

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
# 2️⃣  FUNGSI EKSTRAKSI MUTASI REKENING
# =========================================================
def extract_mutasi_from_bytes(pdf_bytes, pdf_name):
    """
    Mengekstrak rekap mutasi rekening BRI (BRISIM) dari PDF.
    Mengembalikan dict satu baris rekap per file, atau None jika gagal.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"

    # --- Nama nasabah ---
    nama = "(Tidak ditemukan)"
    nm = re.search(r'Statement Date\n:\n[\d/]+\n([A-Z][A-Z\s]+?)\s*\n', text)
    if nm:
        nama = nm.group(1).strip()

    # --- Periode transaksi  (DD/MM/YY - DD/MM/YY) ---
    bulan_str = "(Tidak ditemukan)"
    tahun_str = "(Tidak ditemukan)"
    pm = re.search(
        r'Periode Transaksi\s*\nTransaction Period\s*\n:\s*\n(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})',
        text
    )
    if pm:
        # Ambil bulan & tahun dari tanggal MULAI periode
        start = pm.group(1)           # DD/MM/YY
        parts = start.split('/')
        bulan_str = BULAN_MAP.get(parts[1], parts[1])
        tahun_str = '20' + parts[2]

    # --- Saldo Awal, Total Debet, Total Kredit, Saldo Akhir ---
    def parse_rp(s):
        """Konversi string '151,847.00' ke float."""
        try:
            return float(s.replace(',', ''))
        except Exception:
            return 0.0

    saldo_awal     = 0.0
    total_debet    = 0.0
    total_kredit   = 0.0
    saldo_akhir    = 0.0

    sm = re.search(
        r'Saldo Awal\nOpening Balance\nTotal Transaksi Debet\nTotal Debit Transaction\n'
        r'Total Transaksi Kredit\nTotal Credit Transaction\nSaldo Akhir\nClosing Balance\n'
        r'([\d,\.]+)\n([\d,\.]+)\n([\d,\.]+)\n([\d,\.]+)',
        text
    )
    if sm:
        saldo_awal   = parse_rp(sm.group(1))
        total_debet  = parse_rp(sm.group(2))
        total_kredit = parse_rp(sm.group(3))
        saldo_akhir  = parse_rp(sm.group(4))

    def fmt_rp(v):
        """Format float ke string Rupiah: 151,847.00"""
        return f"{v:,.2f}"

    return {
        "Nama": nama,
        "Bulan": bulan_str,
        "Tahun": tahun_str,
        "Saldo Awal (Opening Balance)": fmt_rp(saldo_awal),
        "Total Transaksi Debet (Total Debit Transaction)": fmt_rp(total_debet),
        "Total Transaksi Kredit (Total Credit Transaction)": fmt_rp(total_kredit),
        "Saldo Akhir (Closing Balance)": fmt_rp(saldo_akhir),
        # Nilai numerik untuk perhitungan baris total
        "_saldo_awal_num":    saldo_awal,
        "_total_debet_num":   total_debet,
        "_total_kredit_num":  total_kredit,
        "_saldo_akhir_num":   saldo_akhir,
        "Nama File PDF": pdf_name,
    }


# =========================================================
# 3️⃣  FUNGSI HISTORY SLIK (tidak berubah)
# =========================================================
def process_history_with_filter(df, filename, folder="history"):
    if not os.path.exists(folder):
        os.makedirs(folder)

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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(filename)[0]
    filepath = os.path.join(folder, f"{base_name}_filtered_{timestamp}.xlsx")

    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        filtered_df.to_excel(writer, sheet_name='Data Terfilter', index=False)
        result_df.to_excel(writer, sheet_name='Ringkasan per Nama', index=False)
        df_processed.to_excel(writer, sheet_name='Data Original', index=False)

    return filepath, f"Berhasil memproses {len(filtered_df)} record dari {len(df)} total record"


# =========================================================
# 4️⃣  HELPER: buat Excel mutasi dengan baris TOTAL
# =========================================================
def build_mutasi_excel(df_mutasi: pd.DataFrame) -> BytesIO:
    """
    Tambahkan baris TOTAL di bagian bawah kolom numerik,
    lalu kembalikan sebagai BytesIO Excel.
    """
    display_cols = [
        "Nama", "Bulan", "Tahun",
        "Saldo Awal (Opening Balance)",
        "Total Transaksi Debet (Total Debit Transaction)",
        "Total Transaksi Kredit (Total Credit Transaction)",
        "Saldo Akhir (Closing Balance)",
        "Nama File PDF",
    ]
    df_show = df_mutasi[display_cols].copy()

    # Baris total
    total_debet  = df_mutasi["_total_debet_num"].sum()
    total_kredit = df_mutasi["_total_kredit_num"].sum()
    total_saldo_akhir = df_mutasi["_saldo_akhir_num"].sum()

    total_row = {
        "Nama": "TOTAL",
        "Bulan": "",
        "Tahun": "",
        "Saldo Awal (Opening Balance)": "",
        "Total Transaksi Debet (Total Debit Transaction)": f"{total_debet:,.2f}",
        "Total Transaksi Kredit (Total Credit Transaction)": f"{total_kredit:,.2f}",
        "Saldo Akhir (Closing Balance)": f"{total_saldo_akhir:,.2f}",
        "Nama File PDF": "",
    }
    df_total = pd.concat([df_show, pd.DataFrame([total_row])], ignore_index=True)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_total.to_excel(writer, index=False, sheet_name='Rekap Mutasi')

        # Auto-fit kolom (opsional, agar rapi)
        ws = writer.sheets['Rekap Mutasi']
        for col in ws.columns:
            max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    buf.seek(0)
    return buf


# =========================================================
# 5️⃣  STREAMLIT UI
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
        with st.spinner("Memproses file SLIK... ⏳"):
            for uf in uploaded_files:
                df = extract_slik_data_from_bytes(uf.read(), uf.name)
                if not df.empty:
                    all_data.append(df)

        if all_data:
            df_all = pd.concat(all_data, ignore_index=True)
            st.success(f"✅ Berhasil memproses {len(uploaded_files)} file PDF!")

            with st.expander("👁️ Preview Data", expanded=True):
                st.dataframe(df_all, use_container_width=True)

            # --- Simpan History dengan Filter ---
            st.subheader("💾 Simpan ke History dengan Filter")
            st.info("""
            **Filter:** Jenis Penggunaan = "Modal Kerja" **&** Kondisi = "Fasilitas"  
            Disimpan dalam 3 sheet: Data Terfilter | Ringkasan per Nama | Data Original
            """)

            col1, col2 = st.columns([2, 1])
            with col1:
                history_filename = st.text_input(
                    "Nama file history:",
                    value=f"SLIK_Filtered_{datetime.now().strftime('%Y%m%d')}",
                )
            with col2:
                st.write("")
                save_btn = st.button("💾 Simpan History", type="primary")

            if save_btn and history_filename.strip():
                fn = history_filename.strip()
                if not fn.endswith('.xlsx'):
                    fn += '.xlsx'
                with st.spinner("Menyimpan..."):
                    try:
                        path, msg = process_history_with_filter(df_all, fn)
                        if path:
                            st.success(f"✅ {msg}")
                            st.success(f"📁 Tersimpan di: `{path}`")
                            # Preview filter result
                            mask = (
                                df_all['Jenis Penggunaan'].str.contains('Modal Kerja', case=False, na=False) &
                                df_all['Kondisi'].str.contains('Fasilitas', case=False, na=False)
                            )
                            st.dataframe(df_all[mask].head(10), use_container_width=True)
                        else:
                            st.warning(f"⚠ {msg}")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")

            # --- Download Excel lengkap ---
            st.subheader("📥 Download Hasil Ekstraksi")
            buf = BytesIO()
            df_all.to_excel(buf, index=False)
            buf.seek(0)
            st.download_button(
                "⬇️ Unduh Excel Lengkap",
                data=buf,
                file_name=f"SLIK_Extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # --- Statistik ---
            with st.expander("📈 Statistik Data"):
                c1, c2, c3 = st.columns(3)
                mask_mk = df_all['Jenis Penggunaan'].str.contains('Modal Kerja', case=False, na=False)
                mask_fa = df_all['Kondisi'].str.contains('Fasilitas', case=False, na=False)
                c1.metric("Total Record", len(df_all))
                c1.metric("Nama Unik", df_all['Nama Sesuai Identitas'].nunique())
                c2.metric("Modal Kerja", mask_mk.sum())
                c2.metric("Kondisi Fasilitas", mask_fa.sum())
                c3.metric("Modal Kerja + Fasilitas", (mask_mk & mask_fa).sum())
        else:
            st.warning("⚠ Tidak ada data yang berhasil diekstrak.")

# ===========================================================
# MODE B : REKAP MUTASI REKENING
# ===========================================================
else:
    st.subheader("🏦 Rekap Mutasi Rekening")
    st.write("Unggah satu atau beberapa file PDF mutasi rekening BRI (format BRISIM).")

    uploaded_files = st.file_uploader(
        "Tarik & lepaskan file PDF Mutasi Rekening di sini",
        type=["pdf"],
        accept_multiple_files=True,
        key="mutasi_uploader",
    )

    if uploaded_files:
        results = []
        errors  = []

        with st.spinner("Memproses file mutasi... ⏳"):
            for uf in uploaded_files:
                try:
                    row = extract_mutasi_from_bytes(uf.read(), uf.name)
                    if row:
                        results.append(row)
                except Exception as e:
                    errors.append(f"{uf.name}: {e}")

        if errors:
            for err in errors:
                st.warning(f"⚠ {err}")

        if results:
            df_mutasi = pd.DataFrame(results)

            st.success(f"✅ Berhasil memproses {len(results)} file PDF!")

            # ---- Preview tabel dengan baris TOTAL ----
            display_cols = [
                "Nama", "Bulan", "Tahun",
                "Saldo Awal (Opening Balance)",
                "Total Transaksi Debet (Total Debit Transaction)",
                "Total Transaksi Kredit (Total Credit Transaction)",
                "Saldo Akhir (Closing Balance)",
                "Nama File PDF",
            ]

            total_debet  = df_mutasi["_total_debet_num"].sum()
            total_kredit = df_mutasi["_total_kredit_num"].sum()
            total_saldo_akhir = df_mutasi["_saldo_akhir_num"].sum()

            total_row = {
                "Nama": "➕ TOTAL",
                "Bulan": "",
                "Tahun": "",
                "Saldo Awal (Opening Balance)": "",
                "Total Transaksi Debet (Total Debit Transaction)": f"{total_debet:,.2f}",
                "Total Transaksi Kredit (Total Credit Transaction)": f"{total_kredit:,.2f}",
                "Saldo Akhir (Closing Balance)": f"{total_saldo_akhir:,.2f}",
                "Nama File PDF": "",
            }

            df_preview = pd.concat(
                [df_mutasi[display_cols], pd.DataFrame([total_row])],
                ignore_index=True
            )

            with st.expander("👁️ Preview Rekap Mutasi", expanded=True):
                # Highlight baris TOTAL
                def highlight_total(row):
                    if str(row["Nama"]).startswith("➕"):
                        return ['background-color: #fff3cd; font-weight: bold'] * len(row)
                    return [''] * len(row)

                st.dataframe(
                    df_preview.style.apply(highlight_total, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )

            # ---- Metrik ringkasan ----
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("File Diproses", len(results))
            c2.metric("Total Debet",   f"Rp {total_debet:,.0f}")
            c3.metric("Total Kredit",  f"Rp {total_kredit:,.0f}")
            c4.metric("Total Saldo Akhir", f"Rp {total_saldo_akhir:,.0f}")

            # ---- Download Excel ----
            st.subheader("📥 Download Rekap Mutasi")
            excel_buf = build_mutasi_excel(df_mutasi)
            st.download_button(
                "⬇️ Unduh Rekap Mutasi (Excel)",
                data=excel_buf,
                file_name=f"Rekap_Mutasi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
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
