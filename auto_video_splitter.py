"""
Auto Video Splitter — Aplikasi pemotong video otomatis berbasis FFmpeg & Pillow.

Fitur utama:
  • GUI modern menggunakan customtkinter (dark mode).
  • Pilihan durasi split instan (5, 8, 10, 15, 20 menit) + kustom.
  • Stream-copy (-c copy) agar pemotongan instan tanpa re-encoding.
  • Mode Re-encoding untuk pemotongan presisi tinggi.
  • Thumbnail Otomatis: Membuat cover bernomor untuk setiap part video.
  • Memasang cover/artwork langsung ke file MP4 tanpa mengubah timeline/durasi video.
  • Otomatis membuat folder output di lokasi file sumber.
  • Menangani sisa durasi secara akurat.

Dependensi:
  pip install customtkinter pillow
  FFmpeg & FFprobe harus tersedia di PATH sistem.
"""

import os
import re
import json
import math
import tempfile
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import timedelta

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageOps


# ──────────────────────────────────────────────
# Konfigurasi tampilan global
# ──────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Palet warna kustom
COLOR_BG_DARK    = "#0f1117"
COLOR_BG_CARD    = "#1a1d27"
COLOR_BG_INPUT   = "#252836"
COLOR_ACCENT     = "#6c5ce7"
COLOR_ACCENT_HVR = "#7c6cf7"
COLOR_SUCCESS    = "#00cec9"
COLOR_TEXT       = "#e4e6eb"
COLOR_TEXT_DIM   = "#8b8fa3"
COLOR_BORDER     = "#2d3040"
COLOR_RED        = "#ff6b6b"
COLOR_RED_HVR    = "#ff5252"


# ──────────────────────────────────────────────
# Fungsi utilitas FFmpeg / FFprobe
# ──────────────────────────────────────────────

def get_video_duration(filepath: str) -> float:
    """
    Membaca total durasi video (dalam detik) menggunakan ffprobe.
    Mengembalikan float durasi. Raise RuntimeError jika gagal.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        filepath,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        return duration
    except (KeyError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Gagal membaca durasi video. Pastikan FFmpeg/FFprobe terinstal dan ada di PATH."
        ) from exc


# ──────────────────────────────────────────────
# Modul Pengolahan Thumbnail (Pillow)
# ──────────────────────────────────────────────

def get_best_font(size: int) -> ImageFont.FreeTypeFont:
    """Mencari font tebal terbaik dari sistem operasi Windows dengan fallback."""
    candidates = [
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf",
        "C:\\Windows\\Fonts\\impact.ttf",
        "C:\\Windows\\Fonts\\tahomabd.ttf",
    ]
    for font_path in candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def create_numbered_thumbnail(
    image_path: str,
    number: int,
    output_path: str,
    position: str = "bottom_right",
    text_prefix: str = "",
) -> str:
    """
    Membaca gambar thumbnail asli, menambahkan badge nomor part,
    lalu menyimpannya ke file tujuan tanpa mengubah gambar asli.

    Args:
        image_path:  Path file gambar thumbnail sumber.
        number:      Nomor part (1, 2, 3, ...).
        output_path: Path untuk menyimpan thumbnail hasil.
        position:    Posisi nomor ('bottom_right', 'bottom_left', 'top_right', 'top_left', 'center').
        text_prefix: Prefix opsional sebelum nomor (misal 'Part ').

    Returns:
        output_path jika berhasil.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"File thumbnail tidak ditemukan: {image_path}")

    with Image.open(image_path) as raw_img:
        # Perbaiki orientasi otomatis berdasarkan EXIF
        base_img = ImageOps.exif_transpose(raw_img)
        img = base_img.convert("RGBA")
        width, height = img.size

        # Layer overlay untuk gambar badge dengan transparansi
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Skala ukuran font & badge proporsional terhadap ukuran gambar
        ref_dim = min(width, height)
        font_size = max(24, int(ref_dim * 0.13))
        font = get_best_font(font_size)

        text = f"{text_prefix}{number}"

        # Hitung ukuran teks
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        pad_x = int(font_size * 0.45)
        pad_y = int(font_size * 0.28)
        badge_w = text_w + (pad_x * 2)
        badge_h = text_h + (pad_y * 2)

        # Margin dari tepi gambar
        margin_x = int(width * 0.04)
        margin_y = int(height * 0.045)

        if position == "bottom_right":
            bx1 = width - margin_x - badge_w
            by1 = height - margin_y - badge_h
        elif position == "bottom_left":
            bx1 = margin_x
            by1 = height - margin_y - badge_h
        elif position == "top_right":
            bx1 = width - margin_x - badge_w
            by1 = margin_y
        elif position == "top_left":
            bx1 = margin_x
            by1 = margin_y
        elif position == "center":
            bx1 = (width - badge_w) // 2
            by1 = (height - badge_h) // 2
        else:  # Default bottom_right
            bx1 = width - margin_x - badge_w
            by1 = height - margin_y - badge_h

        bx2 = bx1 + badge_w
        by2 = by1 + badge_h

        radius = int(min(badge_w, badge_h) * 0.28)
        outline_w = max(2, int(font_size * 0.04))

        # Gambar kotak badge (gelap semi-transparan dengan border putih kontras)
        draw.rounded_rectangle(
            [bx1, by1, bx2, by2],
            radius=radius,
            fill=(15, 17, 23, 220),
            outline=(255, 255, 255, 230),
            width=outline_w,
        )

        # Posisi teks di tengah-tengah badge
        tx = bx1 + (badge_w - text_w) / 2 - bbox[0]
        ty = by1 + (badge_h - text_h) / 2 - bbox[1]

        # Bayangan teks (drop shadow lembut)
        shadow_offset = max(1, int(font_size * 0.03))
        draw.text((tx + shadow_offset, ty + shadow_offset), text, font=font, fill=(0, 0, 0, 180))

        # Teks utama berwarna putih tebal
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

        # Gabungkan overlay ke gambar dasar
        final_img = Image.alpha_composite(img, overlay)
        final_rgb = final_img.convert("RGB")

        # Pastikan direktori output ada
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        final_rgb.save(output_path, format="JPEG", quality=95)

    return output_path


def attach_thumbnail_to_video(video_path: str, thumbnail_path: str) -> bool:
    """
    Memasangkan file thumbnail sebagai cover/artwork pada file video MP4/MKV
    tanpa re-encoding video utama.

    Args:
        video_path:     Path lengkap ke file video tujuan.
        thumbnail_path: Path lengkap ke file gambar thumbnail (JPG).

    Returns:
        True jika berhasil, False jika gagal.
    """
    if not os.path.isfile(video_path) or not os.path.isfile(thumbnail_path):
        return False

    dir_name = os.path.dirname(video_path)
    file_name = os.path.basename(video_path)
    temp_out = os.path.join(dir_name, f"_temp_cover_{file_name}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-i", thumbnail_path,
        "-map", "0",
        "-map", "1",
        "-c", "copy",
        "-disposition:v:1", "attached_pic",
        "-movflags", "+faststart",
        temp_out,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        if proc.returncode == 0 and os.path.isfile(temp_out) and os.path.getsize(temp_out) > 0:
            # Ganti file asli secara aman
            os.replace(temp_out, video_path)
            return True
        else:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass
            return False
    except Exception:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass
        return False


# ──────────────────────────────────────────────
# Proses Pemotongan Video Utama
# ──────────────────────────────────────────────

def split_video(
    filepath: str,
    segment_minutes: float,
    mode: str = "copy",
    thumbnail_path: str = "",
    thumb_position: str = "bottom_right",
    save_thumb_files: bool = False,
    log_callback=None,
    done_callback=None,
):
    """
    Memotong video menjadi beberapa bagian dengan durasi tertentu dan
    memasang thumbnail cover otomatis jika disediakan.

    Args:
        filepath:         Path lengkap ke file video sumber.
        segment_minutes:  Durasi tiap bagian (dalam menit).
        mode:             Metode pemotongan ('copy' atau 'encode').
        thumbnail_path:   Path ke gambar thumbnail utama (opsional).
        thumb_position:   Posisi nomor pada thumbnail.
        save_thumb_files: Apakah file gambar thumbnail (.jpg) juga disimpan di folder output.
        log_callback:     Fungsi untuk menulis log ke GUI (opsional).
        done_callback:    Fungsi yang dipanggil setelah proses selesai.
    """

    def log(msg: str):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    try:
        # ── 1. Baca durasi total ────────────────────
        total_seconds = get_video_duration(filepath)
        segment_seconds = segment_minutes * 60
        total_parts = math.ceil(total_seconds / segment_seconds)

        total_fmt = str(timedelta(seconds=int(total_seconds)))
        log("=" * 50)
        log(f"📁 File Video : {os.path.basename(filepath)}")
        log(f"⏱  Durasi     : {total_fmt}  ({total_seconds:.1f} detik)")
        log(f"✂  Split      : setiap {segment_minutes} menit → {total_parts} bagian")
        log(f"⚙  Metode     : {'Instan (Stream Copy)' if mode == 'copy' else 'Presisi (Re-encoding)'}")

        has_thumbnail = bool(thumbnail_path and os.path.isfile(thumbnail_path))
        if has_thumbnail:
            log(f"🖼  Thumbnail  : {os.path.basename(thumbnail_path)} (Posisi: {thumb_position})")
            log(f"💾 Simpan JPG : {'Ya' if save_thumb_files else 'Hanya Cover MP4'}")
        else:
            log("🖼  Thumbnail  : (Tidak ada thumbnail yang dipilih)")
        log("=" * 50 + "\n")

        # ── 2. Buat folder output ───────────────────
        src_dir  = os.path.dirname(filepath)
        src_name = Path(filepath).stem          # nama tanpa ekstensi
        ext      = Path(filepath).suffix if mode == "copy" else ".mp4"  # MP4 jika re-encode
        out_dir  = os.path.join(src_dir, f"{src_name}_Splits")
        os.makedirs(out_dir, exist_ok=True)
        log(f"📂 Folder output: {out_dir}\n")

        # ── 3. Loop pemotongan ──────────────────────
        for i in range(total_parts):
            part_num   = i + 1
            start_sec  = i * segment_seconds
            # Durasi bagian ini — bagian terakhir mungkin lebih pendek
            remaining  = total_seconds - start_sec
            duration   = min(segment_seconds, remaining)

            out_file = os.path.join(out_dir, f"{src_name}_Part_{part_num}{ext}")

            start_fmt = str(timedelta(seconds=int(start_sec)))
            dur_fmt   = str(timedelta(seconds=int(duration)))
            log(f"🔄 Memotong Part {part_num}/{total_parts} [{start_fmt} → +{dur_fmt}] ...")

            if mode == "encode":
                cmd = [
                    "ffmpeg",
                    "-y",                       # overwrite tanpa konfirmasi
                    "-ss", str(start_sec),      # posisi awal
                    "-i", filepath,             # input file
                    "-t", str(duration),        # durasi potongan
                    "-c:v", "libx264",          # video codec H.264
                    "-preset", "veryfast",      # preset encoding cepat
                    "-crf", "22",               # visual quality
                    "-c:a", "aac",              # audio codec AAC
                    "-avoid_negative_ts", "make_zero",
                    out_file,
                ]
            else:
                cmd = [
                    "ffmpeg",
                    "-y",                       # overwrite tanpa konfirmasi
                    "-ss", str(start_sec),      # posisi awal
                    "-i", filepath,             # input file
                    "-t", str(duration),        # durasi potongan
                    "-c", "copy",               # STREAM COPY — tanpa re-encoding
                    "-avoid_negative_ts", "make_zero",
                    out_file,
                ]

            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            if proc.returncode != 0:
                log(f"⚠  Peringatan pada Part {part_num}: {proc.stderr[-200:]}")
            else:
                log(f"   ✓ File video Part {part_num} berhasil dibuat")

            # ── 4. Pasang Thumbnail Otomatis ───────────
            if has_thumbnail and os.path.isfile(out_file):
                temp_thumb_path = ""
                try:
                    # Tentukan lokasi file gambar thumbnail
                    if save_thumb_files:
                        thumb_file_dest = os.path.join(out_dir, f"{src_name}_Part_{part_num}_thumb.jpg")
                    else:
                        # Buat di folder temp jika tidak ingin disimpan permanen
                        fd, thumb_file_dest = tempfile.mkstemp(suffix=f"_thumb_{part_num}.jpg")
                        os.close(fd)
                        temp_thumb_path = thumb_file_dest

                    # Buat thumbnail bernomor
                    create_numbered_thumbnail(
                        image_path=thumbnail_path,
                        number=part_num,
                        output_path=thumb_file_dest,
                        position=thumb_position,
                    )

                    # Pasang sebagai cover/artwork ke video
                    success = attach_thumbnail_to_video(out_file, thumb_file_dest)
                    if success:
                        log(f"   🖼 Cover Part {part_num} terpasang (Nomor #{part_num})")
                    else:
                        log(f"   ⚠ Gagal memasang cover pada Part {part_num} (Video tetap aman)")

                except Exception as thumb_err:
                    log(f"   ⚠ Gagal memproses thumbnail Part {part_num}: {thumb_err}")

                finally:
                    # Bersihkan file temp jika ada
                    if temp_thumb_path and os.path.exists(temp_thumb_path):
                        try:
                            os.remove(temp_thumb_path)
                        except Exception:
                            pass

            log(f"✅ Part {part_num} selesai → {os.path.basename(out_file)}\n")

        log("=" * 50)
        log(f"🎉 SELESAI! {total_parts} file tersimpan di:")
        log(f"   {out_dir}")
        log("=" * 50)

    except Exception as exc:
        log(f"\n❌ ERROR: {exc}")

    finally:
        if done_callback:
            done_callback()


# ──────────────────────────────────────────────
# Kelas Aplikasi Utama (GUI)
# ──────────────────────────────────────────────

class AutoVideoSplitter(ctk.CTk):
    """Jendela utama aplikasi Auto Video Splitter."""

    PRESET_OPTIONS = ["5 menit", "8 menit", "10 menit", "15 menit", "20 menit"]

    POSITION_MAP = {
        "Kanan Bawah": "bottom_right",
        "Kiri Bawah": "bottom_left",
        "Kanan Atas": "top_right",
        "Kiri Atas": "top_left",
        "Tengah": "center",
    }

    def __init__(self):
        super().__init__()

        # ── Properti jendela ─────────────────────
        self.title("Auto Video Splitter — Auto Cover Thumbnail")
        self.geometry("740x900")
        self.minsize(660, 780)
        self.configure(fg_color=COLOR_BG_DARK)

        # State
        self._selected_file: str = ""
        self._selected_thumbnail: str = ""
        self._is_running: bool = False

        # ── Bangun antarmuka ─────────────────────
        self._build_ui()

    # ───────────────────────────────────────────
    # Pembuatan UI
    # ───────────────────────────────────────────

    def _build_ui(self):
        """Menyusun seluruh komponen antarmuka."""

        # Container scrollable agar responsif di semua resolusi layar
        self.scroll_container = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=COLOR_BG_INPUT,
            scrollbar_button_hover_color=COLOR_ACCENT,
        )
        self.scroll_container.pack(fill="both", expand=True, padx=16, pady=16)

        # ── Header / Judul ───────────────────────
        header_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header_frame,
            text="✂️  Auto Video Splitter",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            header_frame,
            text="v2.0 (Auto Thumbnail)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_ACCENT,
        ).pack(side="left", padx=(10, 0), pady=(6, 0))

        # ── Deskripsi singkat ────────────────────
        ctk.CTkLabel(
            self.scroll_container,
            text="Potong video menjadi beberapa bagian otomatis & pasang thumbnail bernomor sebagai cover video.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", pady=(0, 14))

        # ══════════════════════════════════════════
        # CARD 1 — Pilih Video
        # ══════════════════════════════════════════
        card_file = self._make_card(self.scroll_container, "📁  PILIH VIDEO")

        file_row = ctk.CTkFrame(card_file, fg_color="transparent")
        file_row.pack(fill="x")

        self.btn_browse = ctk.CTkButton(
            file_row,
            text="Pilih Video",
            width=130,
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            command=self._browse_file,
        )
        self.btn_browse.pack(side="left")

        self.lbl_filepath = ctk.CTkLabel(
            file_row,
            text="Belum ada file video dipilih",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
            wraplength=480,
        )
        self.lbl_filepath.pack(side="left", padx=(14, 0), fill="x", expand=True)

        # Label info durasi video
        self.lbl_duration = ctk.CTkLabel(
            card_file,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_SUCCESS,
            anchor="w",
        )
        self.lbl_duration.pack(fill="x", pady=(6, 0))

        # ══════════════════════════════════════════
        # CARD 2 — Pilih Thumbnail (Fitur Baru)
        # ══════════════════════════════════════════
        card_thumb = self._make_card(self.scroll_container, "🖼️  PILIH THUMBNAIL (OPSIONAL)")

        # Baris tombol browse & reset
        thumb_btn_row = ctk.CTkFrame(card_thumb, fg_color="transparent")
        thumb_btn_row.pack(fill="x", pady=(0, 8))

        self.btn_browse_thumb = ctk.CTkButton(
            thumb_btn_row,
            text="Pilih Gambar",
            width=130,
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            command=self._browse_thumbnail,
        )
        self.btn_browse_thumb.pack(side="left")

        self.btn_clear_thumb = ctk.CTkButton(
            thumb_btn_row,
            text="✕ Hapus",
            width=75,
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_BG_INPUT,
            hover_color=COLOR_RED_HVR,
            text_color=COLOR_TEXT_DIM,
            command=self._clear_thumbnail,
        )
        self.btn_clear_thumb.pack(side="left", padx=(8, 0))

        self.lbl_thumbpath = ctk.CTkLabel(
            thumb_btn_row,
            text="Belum ada thumbnail (opsional)",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
            wraplength=400,
        )
        self.lbl_thumbpath.pack(side="left", padx=(12, 0), fill="x", expand=True)

        # Pemisah halus
        sep_thumb = ctk.CTkFrame(card_thumb, height=1, fg_color=COLOR_BORDER)
        sep_thumb.pack(fill="x", pady=(4, 10))

        # Baris opsi posisi nomor & penyimpanan
        opt_thumb_row = ctk.CTkFrame(card_thumb, fg_color="transparent")
        opt_thumb_row.pack(fill="x")

        ctk.CTkLabel(
            opt_thumb_row,
            text="Posisi Nomor:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left", padx=(0, 10))

        self._position_var = tk.StringVar(value="Kanan Bawah")
        self.combo_position = ctk.CTkOptionMenu(
            opt_thumb_row,
            values=list(self.POSITION_MAP.keys()),
            variable=self._position_var,
            width=135,
            height=32,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_BG_INPUT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HVR,
            dropdown_fg_color=COLOR_BG_CARD,
        )
        self.combo_position.pack(side="left", padx=(0, 20))

        self._save_thumb_var = tk.BooleanVar(value=False)
        self.chk_save_thumb = ctk.CTkCheckBox(
            opt_thumb_row,
            text="Simpan file .jpg di folder output",
            variable=self._save_thumb_var,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            border_color=COLOR_BORDER,
        )
        self.chk_save_thumb.pack(side="left")

        # ══════════════════════════════════════════
        # CARD 3 — Durasi Split
        # ══════════════════════════════════════════
        card_dur = self._make_card(self.scroll_container, "⏱  DURASI SPLIT")

        ctk.CTkLabel(
            card_dur,
            text="Pilihan Cepat:",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        self._duration_var = tk.StringVar(value="10 menit")

        preset_frame = ctk.CTkFrame(card_dur, fg_color="transparent")
        preset_frame.pack(fill="x", pady=(0, 12))

        for opt in self.PRESET_OPTIONS:
            ctk.CTkRadioButton(
                preset_frame,
                text=opt,
                variable=self._duration_var,
                value=opt,
                font=ctk.CTkFont(size=12),
                text_color=COLOR_TEXT,
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HVR,
                border_color=COLOR_BORDER,
                command=self._on_preset_selected,
            ).pack(side="left", padx=(0, 16))

        # --- Kustom ---
        sep_dur = ctk.CTkFrame(card_dur, height=1, fg_color=COLOR_BORDER)
        sep_dur.pack(fill="x", pady=(0, 10))

        custom_row = ctk.CTkFrame(card_dur, fg_color="transparent")
        custom_row.pack(fill="x")

        self._use_custom_var = tk.BooleanVar(value=False)
        self.chk_custom = ctk.CTkCheckBox(
            custom_row,
            text="Durasi Kustom (menit):",
            variable=self._use_custom_var,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            border_color=COLOR_BORDER,
            command=self._on_custom_toggled,
        )
        self.chk_custom.pack(side="left")

        self.entry_custom = ctk.CTkEntry(
            custom_row,
            width=90,
            height=32,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_BG_INPUT,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            placeholder_text="cth: 3",
            state="disabled",
        )
        self.entry_custom.pack(side="left", padx=(12, 0))

        # ══════════════════════════════════════════
        # CARD 4 — Metode Pemotongan
        # ══════════════════════════════════════════
        card_mode = self._make_card(self.scroll_container, "⚙️  METODE PEMOTONGAN")

        self._mode_var = tk.StringVar(value="copy")

        mode_row = ctk.CTkFrame(card_mode, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 4))

        self.rad_copy = ctk.CTkRadioButton(
            mode_row,
            text="Instan (Stream Copy)",
            variable=self._mode_var,
            value="copy",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            border_color=COLOR_BORDER,
        )
        self.rad_copy.pack(side="left", padx=(0, 24))

        self.rad_encode = ctk.CTkRadioButton(
            mode_row,
            text="Presisi (Re-encoding)",
            variable=self._mode_var,
            value="encode",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            border_color=COLOR_BORDER,
        )
        self.rad_encode.pack(side="left")

        self.lbl_mode_desc = ctk.CTkLabel(
            card_mode,
            text="💡 Stream Copy memotong instan tanpa render ulang. Cover dipasang langsung sebagai artwork MP4.",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
            wraplength=620,
        )
        self.lbl_mode_desc.pack(fill="x", pady=(4, 0))

        # ══════════════════════════════════════════
        # TOMBOL UTAMA — Mulai Potong
        # ══════════════════════════════════════════
        self.btn_start = ctk.CTkButton(
            self.scroll_container,
            text="🚀  Mulai Potong",
            height=46,
            corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            command=self._start_split,
        )
        self.btn_start.pack(fill="x", pady=(4, 12))

        # ══════════════════════════════════════════
        # CARD 5 — Log / Progress
        # ══════════════════════════════════════════
        card_log = self._make_card(self.scroll_container, "📋  LOG PROSES")

        self.txt_log = ctk.CTkTextbox(
            card_log,
            height=180,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLOR_BG_INPUT,
            text_color=COLOR_TEXT,
            border_color=COLOR_BORDER,
            border_width=1,
            corner_radius=8,
            wrap="word",
            state="disabled",
        )
        self.txt_log.pack(fill="both", expand=True)

        # ── Progress bar ─────────────────────────
        self.progress = ctk.CTkProgressBar(
            self.scroll_container,
            height=4,
            corner_radius=2,
            fg_color=COLOR_BG_CARD,
            progress_color=COLOR_ACCENT,
        )
        self.progress.pack(fill="x", pady=(0, 2))
        self.progress.set(0)

        # ── Footer ──────────────────────────────
        ctk.CTkLabel(
            self.scroll_container,
            text="Menggunakan FFmpeg & Pillow • Cover MP4 tidak mengubah timeline video",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(4, 0))

    # ───────────────────────────────────────────
    # Helper: membuat kartu (card) dengan judul
    # ───────────────────────────────────────────

    def _make_card(self, parent, title: str) -> ctk.CTkFrame:
        """Membuat panel kartu dengan header label."""
        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(10, 6))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        return inner

    # ───────────────────────────────────────────
    # Event Handlers
    # ───────────────────────────────────────────

    def _browse_file(self):
        """Membuka dialog pemilihan file video."""
        filetypes = [
            ("Video Files", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm *.ts *.m4v"),
            ("Semua File", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="Pilih File Video",
            filetypes=filetypes,
        )
        if path:
            self._selected_file = path
            self.lbl_filepath.configure(
                text=path,
                text_color=COLOR_TEXT,
            )
            try:
                dur = get_video_duration(path)
                dur_fmt = str(timedelta(seconds=int(dur)))
                self.lbl_duration.configure(
                    text=f"✓ Durasi Video: {dur_fmt}  ({dur:.1f} detik)",
                    text_color=COLOR_SUCCESS,
                )
            except RuntimeError:
                self.lbl_duration.configure(
                    text="⚠ Tidak bisa membaca durasi (periksa FFprobe di PATH)",
                    text_color=COLOR_RED,
                )

    def _browse_thumbnail(self):
        """Membuka dialog pemilihan gambar thumbnail."""
        filetypes = [
            ("Image Files", "*.jpg *.jpeg *.png *.webp"),
            ("Semua File", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="Pilih Gambar Thumbnail",
            filetypes=filetypes,
        )
        if path:
            try:
                with Image.open(path) as img:
                    w, h = img.size
                self._selected_thumbnail = path
                filename = os.path.basename(path)
                self.lbl_thumbpath.configure(
                    text=f"✓ {filename} ({w}x{h} px)",
                    text_color=COLOR_SUCCESS,
                )
            except Exception as err:
                messagebox.showerror("Error Gambar", f"Gagal membaca file gambar:\n{err}")

    def _clear_thumbnail(self):
        """Menghapus pemilihan thumbnail."""
        self._selected_thumbnail = ""
        self.lbl_thumbpath.configure(
            text="Belum ada thumbnail (opsional)",
            text_color=COLOR_TEXT_DIM,
        )

    def _on_preset_selected(self):
        """Saat user memilih salah satu preset, matikan mode kustom."""
        self._use_custom_var.set(False)
        self.entry_custom.configure(state="disabled")

    def _on_custom_toggled(self):
        """Toggle kolom input kustom aktif/nonaktif."""
        if self._use_custom_var.get():
            self.entry_custom.configure(state="normal")
            self.entry_custom.focus()
        else:
            self.entry_custom.configure(state="disabled")

    # ───────────────────────────────────────────
    # Logging ke textbox
    # ───────────────────────────────────────────

    def _log(self, message: str):
        """Menambahkan pesan ke area log (thread-safe via `after`)."""
        def _append():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", message + "\n")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        self.after(0, _append)

    # ───────────────────────────────────────────
    # Proses Utama Pemotongan
    # ───────────────────────────────────────────

    def _start_split(self):
        """Validasi input lalu jalankan proses split di thread terpisah."""
        if self._is_running:
            messagebox.showwarning("Proses Berjalan", "Tunggu proses saat ini selesai.")
            return

        # Validasi: file sudah dipilih?
        if not self._selected_file:
            messagebox.showerror("Error", "Silakan pilih file video terlebih dahulu!")
            return

        if not os.path.isfile(self._selected_file):
            messagebox.showerror("Error", "File video tidak ditemukan di path tersebut.")
            return

        # Validasi thumbnail jika ada
        if self._selected_thumbnail and not os.path.isfile(self._selected_thumbnail):
            messagebox.showerror("Error", "File thumbnail yang dipilih tidak ditemukan.")
            return

        # Validasi: ambil durasi split
        if self._use_custom_var.get():
            raw = self.entry_custom.get().strip()
            if not raw:
                messagebox.showerror("Error", "Masukkan durasi kustom (dalam menit).")
                return
            try:
                minutes = float(raw)
                if minutes <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Durasi kustom harus berupa angka positif.")
                return
        else:
            preset_text = self._duration_var.get()
            minutes = float(re.findall(r"[\d.]+", preset_text)[0])

        mode = self._mode_var.get()
        thumb_pos = self.POSITION_MAP.get(self._position_var.get(), "bottom_right")
        save_thumbs = self._save_thumb_var.get()

        # Bersihkan log
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

        # UI state: sedang berjalan
        self._is_running = True
        self.btn_start.configure(
            text="⏳  Sedang Memproses...",
            state="disabled",
            fg_color=COLOR_TEXT_DIM,
        )
        self.progress.configure(mode="indeterminate")
        self.progress.start()

        # Jalankan di thread terpisah agar GUI tidak freeze
        thread = threading.Thread(
            target=split_video,
            args=(self._selected_file, minutes),
            kwargs={
                "mode": mode,
                "thumbnail_path": self._selected_thumbnail,
                "thumb_position": thumb_pos,
                "save_thumb_files": save_thumbs,
                "log_callback": self._log,
                "done_callback": self._on_done,
            },
            daemon=True,
        )
        thread.start()

    def _on_done(self):
        """Dipanggil saat proses split selesai (dari thread pekerja)."""
        def _reset_ui():
            self._is_running = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(1.0)
            self.btn_start.configure(
                text="🚀  Mulai Potong",
                state="normal",
                fg_color=COLOR_ACCENT,
            )
        self.after(0, _reset_ui)


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    app = AutoVideoSplitter()
    app.mainloop()
