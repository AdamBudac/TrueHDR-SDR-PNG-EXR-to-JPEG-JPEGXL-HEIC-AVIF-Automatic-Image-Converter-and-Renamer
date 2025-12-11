# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

English guide here: [README.md](README.md)

## Popis

GUI aplikácia pre konverziu, premenovanie a zoradenie vstupných PNG/EXR obrázkov v SDR a HDR formátoch do JPEG, JPEG XL, HEIC a AVIF kodekov

## Funkcie

- Premenovanie s prefixom, číslovaním, auto/ručne zvoleným zerofillom, HDR dostáva `_HDR` suffix, kópie `_DuplicateXX` suffix
- Spracovanie SDR/HDR osobitne; EXR sa páruje k HDR PNG podľa poradia
- Detekcia dostupnosti nástrojov (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) a automatické vypnutie checkboxov chýbajúcich kodekov
- Logy v `output/logging.log`; mapa premenovaní v `output/rename.log` (`old.ext -> new.ext`)
- Uloženie nastavení do `%LOCALAPPDATA%`

## Požiadavky

- **Python 3.12**
- **Python balíky**:
    - `PySide6>=6.6`
    - `pytest>=7.4`
    - `pyinstaller>=6.3` (len pre build EXE)
- **Externé nástroje v PATH**:
    - `ffmpeg` – konverzia obrázkov
    - `cjpeg` – nástroj z balíka `libjpeg-turbo` na export JPEG
    - `cjxl` – súčasť `libjxl` na export JPEG XL
    - `heif-enc` – nástroj z `libheif` na export HEIC
    - `avifenc` – nástroj z `libavif` na export AVIF

## Inštalácia

1. Nainštalujte [Python 3.12](https://www.python.org/)
2. Nainštalujte potrebné balíčky:
```bash
pip install -r requirements.txt
```

## Build (PyInstaller)

```bash
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name TrueHDRConverter script.py
```
Výsledok v `dist/TrueHDRConverter.exe`

## Použitie

- CLI: `python script.py`
- Skompilované EXE: `TrueHDRConverter.exe`
- GUI:
    - **Načítať/Uložiť nastavenia**: podľa potreby
    - **Načítať obrázky**: vyber priečinok s obrázkami
    - **Nastaviť premenovanie**: zapnúť/vypnúť pomenovanie, číslovanie, zerofill  auto/ manual, HDR/SDR
    - **Vybrať kodeky**: kodeky JPEG/JPEG XL/HEIC/AVIF a kvalita pre každý kodek
    - **Spracovanie**: spustiť konverziu, zobrazuje priebeh a stav

## Správanie

- Pri štarte načíta nastavenia z `%LOCALAPPDATA%/TrueHDRConverter/settings.json` (fallback na default)
- Po výbere pracovného priečinka vytvorí `output/`, skopíruje všetky `.png` a `.exr` z koreňa pracovného priečinka do `output/` a pracuje len tam
- Pri premenovaní zapisuje do `output/rename.log` po riadkoch `old.ext -> new.ext`. Chybové a informačné logy idú do `output/logging.log`
- Overwrite dialóg sa zobrazí, ak `output/` nie je prázdny

## Testy

- Pozri `tests/README.md` (unit/integration inštrukcie)

## Referencie

- [ffmpeg](https://www.ffmpeg.org/) v8.0.1-full
- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.1.3-vc-x64
- [libjxl](https://github.com/libjxl/libjxl) v0.11.1 x64
- [libheif](https://github.com/strukturag/libheif) v1.19.5 x64
- [libavif](https://github.com/AOMediaCodec/libavif) v1.3.0 x64

## Licencia

Zadarmo
