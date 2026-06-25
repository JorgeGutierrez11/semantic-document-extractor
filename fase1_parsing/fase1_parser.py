import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

# pyrefly: ignore [missing-import]
import pypandoc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

# Captura bloques <table>…</table> multilinea generados por pandoc.
_TABLE_PATTERN = re.compile(r"<table[\s\S]*?</table>", flags=re.DOTALL | re.IGNORECASE)


@dataclass
class TableData:
    index: int
    html_source: str        # Cadena de texto que contiene el código HTML de la tabla.
    placeholder: str        # "<!-- TABLE_N -->" insertado en el MD
    document_stem: str      # Nombre del archivo DOCX sin extensión.
    llm_summary: str = ""   # Resumen generado por el LLM.
    metadata: dict = field(default_factory=dict)  # Metadatos adicionales.


@dataclass
class ParsedDocument:
    source_path: str             
    filename: str                
    stem: str                                               # Nombre del archivo DOCX sin extensión.
    markdown_content: str = ""                              # Contenido del archivo DOCX en formato Markdown.
    tables: list[TableData] = field(default_factory=list)   # Lista de tablas extraídas.
    metadata: dict = field(default_factory=dict)            # Metadatos adicionales.
    parsing_errors: list[str] = field(default_factory=list)

# Función para extraer tablas del Markdown y reemplazarlas con marcadores de posición
def _extract_and_replace_tables(markdown_raw: str, document_stem: str) -> tuple[str, list[TableData]]:

    matches = list(_TABLE_PATTERN.finditer(markdown_raw))

    if not matches:
        logger.info("  No se encontraron tablas HTML en el output de pandoc.")
        return markdown_raw, []

    logger.info(f"  {len(matches)} tabla(s) detectada(s).")

    tables: list[TableData] = []
    markdown = markdown_raw

    for i, match in enumerate(reversed(matches)):
        real_index = len(matches) - 1 - i
        html_source = match.group(0)

        # Placeholder que queda en el MD. Sintaxis de comentario HTML
        placeholder = f"<!-- TABLE_{real_index} -->"

        tables.append(TableData(
            index=real_index,
            html_source=html_source,
            placeholder=placeholder,
            document_stem=document_stem,
        ))

        start, end = match.start(), match.end()
        markdown = markdown[:start] + placeholder + markdown[end:]

    tables.sort(key=lambda t: t.index)
    return markdown, tables

# Función para convertir un DOCX a Markdown limpio + lista de TableData.
def parse_docx_to_markdown(docx_path: Path) -> ParsedDocument:
    doc = ParsedDocument(
        source_path=str(docx_path),
        filename=docx_path.name,
        stem=docx_path.stem,
    )

    try:
        markdown_raw = pypandoc.convert_file(
            str(docx_path),
            to="markdown-pipe_tables-grid_tables-multiline_tables",
            format="docx+styles",
            extra_args=[
                "--wrap=none",
                "--markdown-headings=atx",
            ]
        )
        logger.info(f"  pandoc: {len(markdown_raw):,} chars en bruto")

        markdown, tables = _extract_and_replace_tables(markdown_raw, docx_path.stem)
        doc.markdown_content = markdown
        doc.tables = tables

    except RuntimeError as e:
        msg = f"pandoc falló procesando {docx_path.name}: {e}"
        doc.parsing_errors.append(msg)
        logger.error(f"❌ {msg}")

    return doc

# Función para ejecutar la fase 1
def run_phase1(input_dir: Path, output_dir: Path) -> list[ParsedDocument]:
    output_dir.mkdir(parents=True, exist_ok=True) # Crea el directorio de salida

    docx_files = sorted(input_dir.glob("*.docx"))
    if not docx_files:
        raise FileNotFoundError(f"No se encontraron .docx en: {input_dir}")

    logger.info(f"📂 {len(docx_files)} DOCX encontrados en {input_dir}")
    results: list[ParsedDocument] = []

    for docx_path in docx_files:
        logger.info(f"\n🔄 {docx_path.name}")
        doc = parse_docx_to_markdown(docx_path)

        if not doc.parsing_errors:
            md_path = output_dir / f"{doc.stem}.md"
            md_path.write_text(doc.markdown_content, encoding="utf-8")

            if doc.tables:
                tables_dir = output_dir / f"{doc.stem}_tables"
                tables_dir.mkdir(exist_ok=True)
                for table in doc.tables:
                    tpath = tables_dir / f"table_{table.index}.html"
                    tpath.write_text(table.html_source, encoding="utf-8")

            logger.info(
                f"  ✅ {doc.stem}.md | "
                f"{len(doc.markdown_content):,} chars | "
                f"{len(doc.tables)} tabla(s)"
            )

        results.append(doc)

    ok = sum(1 for r in results if not r.parsing_errors)
    fail = len(results) - ok
    logger.info(f"\n📊 Fase 1: {ok} OK / {fail} errores")

    if fail > 0:
        for r in results:
            for err in r.parsing_errors:
                logger.warning(f"  • {err}")

    return results

# Punto de entrada del script
if __name__ == "__main__":
    INPUT_DIR = Path("data/raw")
    OUTPUT_DIR = Path("data/processed")

    docs = run_phase1(INPUT_DIR, OUTPUT_DIR)

    sample = next((d for d in docs if not d.parsing_errors), None)
    if sample:
        print(f"\n{'='*60}\nMUESTRA: {sample.filename}\n{'='*60}")
        print(sample.markdown_content[:1000])

        if sample.tables:
            print(f"\n{'='*60}\nTABLA 0 — primeros 400 chars\n{'='*60}")
            print(sample.tables[0].html_source[:400])
        else:
            print("\n⚠️  Sin tablas detectadas. Verifica el .md en data/processed/")
            print("Si la tabla aparece como +---+---+ es grid_table: el flag no aplicó.")
            