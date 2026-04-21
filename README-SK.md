# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

English guide here: [README.md](README.md)

## Popis

GUI a CLI aplikácia pre konverziu, premenovanie a zoradenie vstupných PNG/EXR obrázkov v SDR a HDR formátoch do JPEG, JPEG XL, HEIC a AVIF kodekov.

## Funkcie

- Premenovanie s prefixom, číslovaním, auto/manuálnym zerofillom; HDR dostáva `_HDR` suffix, BW (čiernobiele) dostáva `_BW` suffix, kópie dostávajú `_DuplicateXX`
- Spracovanie SDR/HDR osobitne; podpora pre farebné (Color) a čiernobiele (BW) varianty
- BW detekcia prostredníctvom prípony `_BW` alebo `-2` (nezávisle od veľkosti písmen)
- Detekcia dostupnosti nástrojov (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) a automatické vypnutie checkboxov chýbajúcich kodekov
- Tlačidlo Stop pre prerušenie spracovania kedykoľvek počas behu
- Plnohodnotné CLI rozhranie s `argparse` pre automatizáciu / skriptovanie
- Logy v `output/logging.log`; mapa premenovaní v `output/rename.log` (`old.ext -> new.ext`)
- Uloženie nastavení do `%APPDATA%`

## Štruktúra projektu

```
src/
├── main.py          – Vstupný bod (GUI alebo CLI cez --cli vlajku)
├── cli.py           – argparse CLI rozhranie
├── gui.py           – PySide6 GUI (Hlavné okno)
├── styles.qss       – Qt štýly
├── models.py        – AppSettings dataclass, ImageType enum, konštanty
├── config.py        – Načítanie/uloženie nastavení, cesty, detekcia nástrojov
├── classifier.py    – Klasifikácia obrázkov (SDR/HDR, Color/BW)
├── renamer.py       – Zostavenie a vykonanie plánu premenovania
├── converter.py     – Konverzia obrázkov (wrappery pre externé nástroje)
└── worker.py        – Vlákno na spracovanie na pozadí (QThread)
```

## Požiadavky

- **Python 3.13**
- **Python balíky:**
  - `PySide6==6.11.0`
  - `pytest==9.0.2`
  - `pyinstaller==6.19.0` (len pre build EXE)
- **Externé nástroje v PATH:**
  - `ffmpeg` – konverzia obrázkov
  - `cjpeg` – nástroj z balíka `libjpeg-turbo` na export JPEG
  - `cjxl` – súčasť `libjxl` na export JPEG XL
  - `heif-enc` – nástroj z `libheif` na export HEIC
  - `avifenc` – nástroj z `libavif` na export AVIF

## Inštalácia

1. Nainštalujte [Python 3.13](https://www.python.org/)
2. Nainštalujte potrebné závislosti:

```bash
pip install -r requirements.txt
```

## Build (PyInstaller)

Použite pribalený skript pre zostavenie:

```bash
python tools/build_exe.py
```

Toto spustí PyInstaller so všetkými potrebnými prepínačmi (`--onefile`, `--noconsole`, `--clean`, `--noconfirm`) a automaticky pribalí `styles.qss`. Výsledok nájdete v `dist/TrueHDRConverter.exe`.

Prípadne môžete spustiť PyInstaller manuálne:

```bash
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name TrueHDRConverter --add-data "src/styles.qss;src" src/main.py
```

## Použitie

### Režim GUI

```bash
python src/main.py
```

Alebo skompilované EXE: `TrueHDRConverter.exe`

Pracovný postup v GUI:

- **Načítať/Uložiť nastavenia**: podľa potreby
- **Načítať obrázky**: vyberte priečinok s obrázkami
- **Nastaviť premenovanie**: prefix, číslovanie, zerofill auto/manuálne
- **Vybrať kodeky**: kodeky JPEG/JPEG XL/HEIC/AVIF a kvalita pre každý kodek
- **Spracovanie**: spustí konverziu, zobrazuje priebeh a stav
- **Stop**: zruší spracovanie počas behu

### Režim CLI

```bash
python src/main.py --cli --input ./photos
python src/main.py --cli --input ./photos --prefix "Vacation_" --quality-jpeg 90
python src/main.py --cli --input ./photos --settings settings.json --overwrite
python src/main.py --cli --help
```

## Klasifikácia obrázkov

Súbory sú klasifikované na základe ich prípon a suffixov v názve (nezávisle od veľkosti písmen):

| Vzor (prípona/suffix)                 | Typ                   |
| ------------------------------------- | --------------------- |
| `photo.png`                           | SDR Farebné (Color)   |
| `photo-2.png`, `photo_BW.png`         | SDR Čiernobiele (BW)  |
| `photo_HDR.png`                       | HDR Farebné (Color)   |
| `photo-2_HDR.png`, `photo_BW_HDR.png` | HDR Čiernobiele (BW)  |
| `photo_HDR.exr`                       | HDR Farebné (EXR)     |
| `photo-2_HDR.exr`, `photo_BW_HDR.exr` | HDR Čiernobiele (EXR) |

## Správanie

- Pri štarte hľadá aplikácia nastavenia najprv v `data/settings.json` (portable režim). Ak ich nenájde, načíta z `%APPDATA%/TrueHDRConverter/settings.json` (s fallbackom na predvolené nastavenia).
- Po výbere pracovného priečinka vytvorí zložku `output/`, skopíruje všetky `.png` a `.exr` z koreňa tohto priečinka do `output/` a pracuje výlučne tam.
- Pri premenovávaní zapisuje riadok po riadku do `output/rename.log` vo formáte `old.ext -> new.ext`; chybové a informačné logy sa ukladajú do `output/logging.log`.
- Ak zložka `output/` nie je prázdna, zobrazí sa dialóg pre prepísanie súborov (overwrite).
- Stlačenie tlačidla **Stop** okamžite ukončí všetky bežiace konverzné procesy (agresívne zrušenie).

## Testy

Projekt obsahuje dva druhy testov, oba napísané pre `pytest`:

1. **Unit testy** (`tests/unit_tests.py`)
   - Testujú izolované komponenty, napr. logiku `classifier.py`, orezávanie hodnôt v `config.py` a výpočty pre zero-fill.
   - Spustenie: `python -m pytest tests/unit_tests.py -v`

2. **Integračný test** (`tests/integration_test.py`)
   - Testuje kompletnú pipelinu od začiatku do konca prostredníctvom `ProcessingWorker`.
   - Využíva `unittest.mock` na simuláciu `ffmpeg` a ďalších externých nástrojov, vďaka čomu zbehne okamžite a nevyžaduje inštaláciu skutočných nástrojov v systéme ani reálne obrázky.
   - Spustenie: `python -m pytest tests/integration_test.py -v`

_Poznámka: Pre úspešné prebehnutie testov nepotrebujete mať vo vašom PATH prostredí nainštalované žiadne externé nástroje (ako ffmpeg)._

## Referencie

- [ffmpeg](https://www.ffmpeg.org/) v8.0.1-full
- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.1.3-vc-x64
- [libjxl](https://github.com/libjxl/libjxl) v0.11.1 x64
- [libheif](https://github.com/strukturag/libheif) v1.19.5 x64
- [libavif](https://github.com/AOMediaCodec/libavif) v1.3.0 x64

_Poznámka: Aplikácia by mala bez problémov fungovať aj s novšími verziami týchto knižníc._

## Licencia

Zadarmo
