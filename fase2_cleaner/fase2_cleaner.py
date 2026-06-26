import logging
import re
from pathlib import Path

# Damos formato al log 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def _remove_pandoc_divs(text: str) -> str:
    """
    Patrón:
        ::: {custom-style="Normal"}   ← línea de apertura
        Contenido del párrafo          ← preservado en grupo 1
        :::                            ← línea de cierre
    """
    return re.sub(
        r'^:::[ \t]+\{[^}]+\}[ \t]*\n([\s\S]*?)^:::[ \t]*\n?',
        r'\1',
        text,
        flags=re.MULTILINE
    )


def _remove_images(text: str) -> str:
    """
    Patrón:
        ![](/media/image.png){width="6.26in" height="2.8in"}
    """
    text = re.sub(r'!\[.*?\]\([^)]*\)\{[^}]*\}', '', text)
    # Limpiar líneas que quedaron completamente vacías
    text = re.sub(r'^[ \t]+$', '', text, flags=re.MULTILINE)
    return text


def _fix_hard_linebreaks(text: str) -> str:
    """
    Patrón:
        Salto de linea forzado: '\' 
    """
    return re.sub(r'\\\n', ' ', text)


def _clean_underline_spans(text: str) -> str:
    """
    Patrón: 
        [957]{.underline}   →   957
        [2°]{.underline}    →   2°
    """
    return re.sub(r'\[([^\]]+)\]\{\.underline\}', r'\1', text)


def _fix_escaped_lists(text: str) -> str:
    """
    Patrón:
        1\. Primero   →   1. Primero
        \- Bullet     →   - Bullet
    """
    text = re.sub(r'^(\d+)\\\.', r'\1.', text, flags=re.MULTILINE)
    text = re.sub(r'^\\-', r'-', text, flags=re.MULTILINE)
    text = re.sub(r'^([a-zA-Z])\\\)', r'\1.)', text, flags=re.MULTILINE)
    return text


def _merge_split_bold(text: str) -> str:
    """
    Patrón:
        **Artículo** **29. Título**   →   **Artículo 29. Título**
        **Parágrafo** **1.**          →   **Parágrafo 1.**
    """
    return re.sub(r'\*\*([^\*\n]+)\*\*[ \t]+\*\*', r'**\1 ', text)


def _normalize_blank_lines(text: str) -> str:
    """
    Patrón:
        Colapsa 3 o más líneas en blanco consecutivas a exactamente una.
    """
    return re.sub(r'\n{3,}', '\n\n', text)

def _fix_degree_symbols(text: str) -> str:
    """
    Patrón:
        **Parágrafo 1**°**.**   →   **Parágrafo 1°.**
        **Parágrafo 4**°        →   **Parágrafo 4°**
    """
    # Corregir caso especial en Ley 1010 Artículo 1 (ya con negritas unificadas)
    text = re.sub(r'\*\*Artículo[ \t]+1\*°\*\*\*\*\.[ \t]+\*\*', r'**Artículo 1°**. ***', text)

    text = re.sub(r'\*\*([^*]+)\*\*°\*\*([^*]*)\*\*', r'**\1°\2**', text)
    text = re.sub(r'\*\*([^*]+)\*\*°(?!\*)', r'**\1°**', text)

    return text


def _fix_bold_italic_suffixes(text: str) -> str:
    """
    Patrón:
        **Artículo 33. *Vigencia y derogatorias****.*   →   **Artículo 33. *Vigencia y derogatorias.***
    """
    return re.sub(r'\*\*\*\*([.,;:]*)\*', r'\1***', text)

# Creamos un arreglo de tuplas con el nombre de la función y la función 
_CLEANING_OPS = [
    ("Pandoc divs",       _remove_pandoc_divs),
    ("Imágenes",          _remove_images),
    ("Saltos duros",      _fix_hard_linebreaks),
    ("Underline spans",   _clean_underline_spans),
    ("Listas escapadas",  _fix_escaped_lists),
    ("Bold partido",      _merge_split_bold),
    ("Líneas en blanco",  _normalize_blank_lines),
    ("Grados",            _fix_degree_symbols),
    ("Sufijos bold-italic", _fix_bold_italic_suffixes),
]

# Función para limpiar el markdown 
def clean_markdown(text: str, stem: str = "") -> str:
    for name, fn in _CLEANING_OPS:
        before = len(text)
        text = fn(text)
        logger.debug(f"  [{stem}] {name}: −{before - len(text):,} chars")
    return text

# Runner de fase — opera sobre archivos en disco
def run_phase2(input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Buscamos los archivos md y los ordenamos
    md_files = sorted(input_dir.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No se encontraron .md en: {input_dir}")

    logger.info(f"📂 {len(md_files)} archivos .md encontrados")

    # Limpiamos cada archivo
    for md_path in md_files:
        raw = md_path.read_text(encoding="utf-8")
        cleaned = clean_markdown(raw, stem=md_path.stem)

        out_path = output_dir / md_path.name
        out_path.write_text(cleaned, encoding="utf-8")

        reduction = len(raw) - len(cleaned)
        pct = reduction / len(raw) * 100 if raw else 0
        logger.info(f"  ✅ {md_path.name} | −{reduction:,} chars ({pct:.1f}%)")


if __name__ == "__main__":
    INPUT_DIR  = Path("../fase1_parsing/data/processed")
    OUTPUT_DIR = Path("data/processed")

    run_phase2(INPUT_DIR, OUTPUT_DIR)

    # Inspección rápida: muestra los primeros 800 chars del primer archivo limpio
    sample = next(OUTPUT_DIR.glob("*.md"), None)
    if sample:
        print(f"\n{'='*60}\nMUESTRA: {sample.name}\n{'='*60}")
        print(sample.read_text(encoding="utf-8")[:800])