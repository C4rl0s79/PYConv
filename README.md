# PYConv — Plex Converter GUI

**Multi-GPU AV1/HEVC batch encoder z Copyparty HTTP pipeline.**

> Konwertuje bibliotekę Plex do AV1/HEVC z automatycznym doborem jakości (CQ auto, VMAF target search, HQ complexity probe). Obsługuje dwa GPU równolegle z pełną weryfikacją SHA-256.

---

## Wymagania systemowe

| Komponent | Minimalne | Zalecane |
|---|---|---|
| System | Windows 10 64-bit | Windows 11 |
| Python | 3.10+ | 3.11+ |
| FFmpeg | 6.0+ | 7.x (z NVENC/QSV/AMF) |
| GPU | NVENC (RTX 20xx+) | RTX 40xx / Intel Arc |
| RAM | 4 GB | 8 GB+ |

## Instalacja

```bash
git clone https://github.com/C4rl0s79/PYConv.git
cd PYConv
pip install -r requirements.txt
```

## Uruchomienie

```bash
python -m pyconv
# lub
pyconv
```

## Funkcje

- **2x GPU równolegle** — NVENC + QSV lub dwa NVENC
- **Auto-CQ** — dobór na podstawie BPP (bits per pixel) i kodeka źródłowego
- **HQ mode** — complexity probe (scene change rate) + VMAF target search (binary search)
- **Copyparty HTTP pipeline** — PREFETCH → ENCODE → UPLOAD z flow control
- **SHA-256 weryfikacja** — każdy plik weryfikowany po enkodowaniu i po uploadzien
- **Skip logic** — pomija jeśli wynik większy lub oszczędność < minimum
- **Test mode** — enkoduje sample, mierzy VMAF, zapisuje raport JSON
- **Anime mode** — minimalny GQ dla treści animowanych

## Obsługiwane enkodery

| Enkoder | Typ | Karta |
|---|---|---|
| `av1nvenc` | AV1 | NVIDIA RTX 30xx+ |
| `hevcnvenc` | HEVC | NVIDIA (Maxwell+) |
| `av1qsv` | AV1 | Intel Arc / 11th gen+ |
| `hevcqsv` | HEVC | Intel QSV |
| `av1amf` | AV1 | AMD RX 6000+ |
| `hevcamf` | HEVC | AMD GCN+ |
| `libx265` | HEVC | CPU |
| `libsvtav1` | AV1 | CPU |

## Konfiguracja

Ustawienia zapisywane automatycznie do `pyconv_session.json` w katalogu roboczym.

## Licencja

MIT
