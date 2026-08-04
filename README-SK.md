# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

English guide here: [README.md](README.md)

## Popis

GUI a CLI aplikácia pre konverziu, premenovanie a zoradenie vstupných PNG/EXR/JPG HDR obrázkov v SDR a HDR formátoch do JPEG, JPEG XL, HEIC a AVIF kodekov.

## Funkcie

- Premenovanie s prefixom, číslovaním, auto/manuálnym zerofillom; HDR dostáva `_HDR` suffix, BW (čiernobiele) dostáva `_BW` suffix, kópie dostávajú `_DuplicateXX`
- Spracovanie SDR/HDR osobitne; podpora pre farebné (Color) a čiernobiele (BW) varianty
- BW detekcia prostredníctvom prípony `_BW` alebo `-2` (nezávisle od veľkosti písmen)
- Detekcia dostupnosti nástrojov (`cjpeg`, `cjxl`, `heif-enc`, `avifenc`) a automatické vypnutie checkboxov chýbajúcich kodekov
- Jeden opakovaný pokus pri zlyhaní externého príkazu (najviac dva pokusy celkom); pri opakovanom zlyhaní pokračovanie ďalším nezávislým kodekom a obrázkom
- Tlačidlo Stop pre prerušenie spracovania kedykoľvek počas behu
- Plnohodnotné CLI rozhranie s `argparse` pre automatizáciu / skriptovanie
- Finálne modálne okno **Processing summary** s počtami spracovaných, úspešných, čiastočne úspešných, chybných a preskočených obrázkov aj opakovaných príkazov
- Kompletný log v `output/logging.log`; mapa premenovaní v `output/rename.log` (`old.ext -> new.ext`); definitívne chyby v `output/errors.log`
- HDR JPEG/JPG súbory (s príponou `_HDR`) sú skopírované a premenované spolu s ich HDR PNG náprotivkami (nie sú konvertované, pretože ich nie je možné vhodne prekódovať)
- Uloženie nastavení do `%APPDATA%`

## Štruktúra projektu

```
src/
├── main.py          – Vstupný bod (GUI alebo CLI cez --cli vlajku)
├── cli.py           – argparse CLI rozhranie
├── gui.py           – PySide6 GUI (Hlavné okno)
├── summary_dialog.py – Modálne okno s finálnym súhrnom spracovania
├── styles.qss       – Qt štýly
├── models.py        – AppSettings dataclass, ImageType enum, konštanty
├── results.py       – Výsledkové modely príkazov, obrázkov a celého spracovania
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
  - `cjpeg` – nástroj z balíka `libjpeg-turbo` na priamy export SDR PNG do JPEG
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
- **Spracovanie**: spustí konverziu a zobrazuje priebeh a stav; po dokončení samostatné modálne okno **Processing summary** zobrazí finálne počty a výsledok
- **Stop**: zruší spracovanie počas behu

#### Výsledky v okne Processing summary

Hlavné okno zostáva nezmenené a otvorené. Po skončení behu sa nad ním zobrazí
samostatné modálne okno **Processing summary** s počtami obrázkov, výstupov,
príkazov, opakovaných pokusov, chýb a preskočení pre závislosť. Pri zrušenom
behu zobrazí aj stav zrušenia a počet nespracovaných obrázkov.

| Výsledok | Význam |
| -------- | ------ |
| **Processing completed** | Všetky požadované výstupy vznikli na prvý pokus |
| **Processing completed after retries** | Aspoň jeden príkaz prvýkrát zlyhal, ale uspel na druhý pokus |
| **Processing completed with errors** | Spracovanie dobehlo do konca, ale aspoň jeden požadovaný výstup definitívne zlyhal alebo sa musel preskočiť |
| **Processing cancelled** | Používateľ stlačil **Stop**; okno ukáže dokončenú prácu aj počet nespracovaných obrázkov |
| **Processing failed** | Spracovanie zastavila fatálna chyba pipeline; podrobnosti sú v `logging.log` |

### Režim CLI

```bash
python src/main.py --cli --input ./photos
python src/main.py --cli --input ./photos --prefix "Vacation_" --quality-jpeg 90
python src/main.py --cli --input ./photos --settings settings.json --overwrite
python src/main.py --cli --help
```

Návratové kódy CLI:

| Kód | Význam |
| --- | ------ |
| `0` | Spracovanie skončilo úspešne, vrátane príkazov zachránených opakovaným pokusom |
| `1` | Vstupný priečinok neexistuje alebo je výstupný priečinok neprázdny a nebol použitý parameter `--overwrite` |
| `2` | Neplatné argumenty CLI alebo fatálna chyba, ktorá zastavila pipeline |
| `3` | Spracovanie sa dokončilo, ale aspoň jedna operácia pre obrázok alebo kodek definitívne zlyhala |

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
| `photo_HDR.jpg`                       | HDR Farebné (JPG)     |
| `photo-2_HDR.jpg`, `photo_BW_HDR.jpg` | HDR Čiernobiele (JPG) |

EXR a JPG/JPEG HDR súbory nie sú konvertované — sú iba skopírované a premenované tak, aby zodpovedali ich HDR PNG náprotivkám. Ne-HDR JPEG súbory vo vstupnom priečinku sú ignorované.

## Správanie

- Pri štarte hľadá aplikácia nastavenia najprv v `data/settings.json` (portable režim). Ak ich nenájde, načíta z `%APPDATA%/TrueHDRConverter/settings.json` (s fallbackom na predvolené nastavenia).
- Po výbere pracovného priečinka vytvorí zložku `output/`, skopíruje všetky `.png`, `.exr` a HDR `.jpg`/`.jpeg` súbory z koreňa tohto priečinka do `output/` a pracuje výlučne tam.
- Každý zlyhaný externý príkaz sa raz zopakuje s rovnakými argumentmi, teda prebehne najviac dvakrát. Ak zlyhá aj druhý pokus, chybný výstup sa preskočí a spracovanie pokračuje ďalším nezávislým kodekom a obrázkom.
- Retry sa vzťahuje na konkrétny príkaz, nie na celý obrázok: už hotové výstupy sa nekódujú znova. Pred druhým pokusom sa odstráni čiastočný dočasný výstup a dočasné názvy sú unikátne pre dané spracovanie obrázka.
- SDR 8-bitové PNG súbory kóduje priamo do JPEG nástroj `cjpeg` z balíka `libjpeg-turbo`, bez medziformátu alebo ďalšieho konverzného nástroja.
- Zrušenie používateľom sa nikdy neopakuje ani nezaznamenáva ako chyba konverzie.
- Po skončení spracovania v GUI zobrazí samostatné modálne okno **Processing summary** počty obrázkov, výstupov, príkazov, opakovaných pokusov, chýb a preskočení pre závislosť. Pri zrušenom behu zobrazí aj stav zrušenia a počet nespracovaných obrázkov.
- Ak zložka `output/` nie je prázdna, zobrazí sa dialóg pre prepísanie súborov (overwrite).
- Stlačenie tlačidla **Stop** okamžite ukončí všetky bežiace konverzné procesy (agresívne zrušenie).

## Log súbory

Pri každom behu sa v `output/` nanovo vytvoria všetky tri logy:

| Súbor | Obsah |
| ----- | ----- |
| `logging.log` | Kompletný chronologický priebeh vrátane každého spustenia príkazu, retry, varovaní a finálneho súhrnu |
| `rename.log` | Úspešné premenovania vo formáte `old.ext -> new.ext` |
| `errors.log` | Iba definitívne chyby príkazov alebo operácií obrázka; po čistom alebo retry úspešnom behu zostane prázdny |

Každá definitívna chyba príkazu sa uloží ako jeden podrobný blok obsahujúci
obrázok, kodek, fázu, kopírovateľný príkaz, oba pokusy, návratový kód,
zachytený `stdout`/`stderr`, finálny Python traceback a prípadný závislý krok,
ktorý sa preskočil. Chyba prvého pokusu, ktorú retry opraví, zostane iba v
`logging.log` a nezapíše sa do `errors.log`.

## Testy

Automatický testovací balík obsahuje:

- `tests/unit_tests.py` – klasifikácia, validácia nastavení, vyhľadávanie súborov a pomocné výpočty zero-fill
- `tests/integration_test.py` – kompletný tok kopírovania, klasifikácie, premenovania a workeru s mockovanými konverziami
- `tests/test_retry_processing.py` – retry, čistenie čiastočných výstupov, závislé preskočenie, zrušenie, `errors.log`, progress a výsledkové počítadlá
- `tests/test_summary_dialog.py` – všetky výsledné stavy a otvorenie samostatného modálneho okna

Spustenie celého balíka:

```bash
python -m pytest tests/unit_tests.py tests/integration_test.py tests/test_retry_processing.py tests/test_summary_dialog.py -v
```

_Poznámka: Pre úspešné prebehnutie testov nepotrebujete mať vo vašom PATH prostredí nainštalované žiadne externé nástroje._

## Referencie

- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.2.0
- [libjxl](https://github.com/libjxl/libjxl) v0.12.0
- [libheif](https://github.com/strukturag/libheif) v1.20.2
- [libavif](https://github.com/AOMediaCodec/libavif) v1.4.2

_Poznámka: Aplikácia by mala bez problémov fungovať aj s novšími verziami týchto knižníc._

## Licencia

Zadarmo
