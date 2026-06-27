"""
Arquitectura: Parent-Child con sliding window
- Parent chunks: fragmentos grandes para contexto en generación (RAG)
- Child chunks:  fragmentos pequeños indexados en el vector store para retrieval
"""

import re
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict

# pyrefly: ignore [missing-import]
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Carpetas
INPUT_DIR = Path("../../fase2_cleaner/data/processed")
OUTPUT_DIR = Path("data/chunks")

# Tamaño de los chunks, sube si tus artículos son muy largos; baja si el contexto se vuelve ruidoso.
PARENT_CHUNK_SIZE = 2000
PARENT_CHUNK_OVERLAP = 200

CHILD_CHUNK_SIZE = 400
CHILD_CHUNK_OVERLAP = 100 # El 25% del chunk size es una heurística común

# DATACLASSES
@dataclass
class ChildChunk:
    content:     str
    metadata:    dict
    child_index: int   # posición dentro del parent (0-based)
    char_start:  int   # offset aproximado dentro del texto del parent

@dataclass
class ParentChunk:
    content:      str
    metadata:     dict
    parent_index: int                            # posición dentro del doc
    children:     list[ChildChunk] = field(default_factory=list)


# EXTRACCIÓN DE METADATA
def extract_doc_metadata(text: str, source_path: Path) -> dict:
    """
    Extrae metadata estructurada del texto de un documento legal colombiano.

    Args:
        text:        Contenido completo del archivo Markdown ya limpio.
        source_path: Path absoluto o relativo al archivo .md.

    Returns:
        dict con los campos encontrados. Siempre incluye 'source' e 'id_norma'.
    """
    metadata = {"source": str(source_path)}

    # Número de ley y año 
    m = re.search(r'[Ll][Ee][Yy]\s+(\d+)\s+[Dd][Ee]\s+(\d{4})', text)
    if m:
        metadata["numero_ley"] = m.group(1)
        metadata["anio"]       = m.group(2)
        metadata["id_norma"]   = f"Ley_{m.group(1)}_{m.group(2)}"
    else:
        # Sin número de ley identificable → usamos el nombre del archivo
        # para que el campo id_norma siempre exista y sea filtrable
        metadata["id_norma"] = source_path.stem

    # Entidad emisora 
    if re.search(r'EL CONGRESO DE COLOMBIA', text, re.IGNORECASE):
        metadata["entidad"] = "Congreso de Colombia"
    elif re.search(r'EL PRESIDENTE DE LA REP[ÚU]BLICA', text, re.IGNORECASE):
        metadata["entidad"] = "Presidencia de la República"

    # Fecha de expedición 
    m2 = re.search(
        r'[Dd]ada[s]? en .+?a los?\s+(\d+)\s+d[ií]as?\s+del?\s+mes\s+de\s+'
        r'([a-záéíóúñA-ZÁÉÍÓÚÑ]+)\s+de\s+(\d{4})',
        text,
    )
    if m2:
        metadata["fecha_expedicion"] = (
            f"{m2.group(1)} de {m2.group(2)} de {m2.group(3)}"
        )

    return metadata


# SPLITTERS
# RecursiveCharacterTextSplitter intenta respetar los separadores en orden:
# primero parte por párrafos (doble salto), luego por línea, luego por
# oración, luego por palabra. Solo llega al carácter individual si no hay
# otra opción — lo que para texto legal casi nunca ocurre.

parent_splitter = RecursiveCharacterTextSplitter(
    chunk_size=PARENT_CHUNK_SIZE,
    chunk_overlap=PARENT_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)

child_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHILD_CHUNK_SIZE,
    chunk_overlap=CHILD_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)

# CHUNKING
def chunk_document(text: str, source_path: Path) -> list[ParentChunk]:
    """
    Aplica el pipeline parent-child a un documento y retorna la estructura
    completa con metadata en cada nivel.

    La metadata del documento se copia en cada chunk (parent y child) para
    que cualquier chunk sea autosuficiente al momento del retrieval — no
    necesitas hacer joins contra una tabla externa para saber de qué ley es.

    Args:
        text:        Texto limpio del documento.
        source_path: Path al archivo, usado para metadata.

    Returns:
        Lista de ParentChunk, cada uno con su lista de ChildChunk.
    """
    doc_metadata  = extract_doc_metadata(text, source_path)
    raw_parents   = parent_splitter.split_text(text)
    parent_chunks = []

    for p_idx, parent_text in enumerate(raw_parents):

        # Metadata del parent: doc-level + posición dentro del documento
        parent_meta = {
            **doc_metadata,
            "chunk_type":   "parent",
            "parent_index": p_idx,
            "parent_total": len(raw_parents),
            "char_count":   len(parent_text),
        }

        parent = ParentChunk(
            content=parent_text,
            metadata=parent_meta,
            parent_index=p_idx,
        )

        # Sliding window dentro del parent 
        raw_children = child_splitter.split_text(parent_text)

        for c_idx, child_text in enumerate(raw_children):

            # char_start: offset del child dentro del parent.
            # Útil para debug y para reconstruir el contexto original.
            char_start = parent_text.find(child_text[:40])

            child_meta = {
                **doc_metadata,
                "chunk_type":   "child",
                "parent_index": p_idx,          # enlace al parent
                "child_index":  c_idx,
                "child_total":  len(raw_children),
                "char_start":   char_start,
                "char_count":   len(child_text),
            }

            parent.children.append(ChildChunk(
                content=child_text,
                metadata=child_meta,
                child_index=c_idx,
                char_start=char_start,
            ))

        parent_chunks.append(parent)

    return parent_chunks


# PERSISTENCIA
# Guardamos dos archivos JSON por documento:
#   - {id_norma}_parents.json  → los parents completos con sus children
#   - {id_norma}_children.json → solo los children aplanados
#
# El archivo de children aplanados es el que vas a usar para cargar en el
# vector store (cada child es un documento independiente con su metadata).
# El archivo de parents lo usas en el paso de generación para recuperar
# el contexto amplio una vez que el retriever encontró el child relevante.

def save_chunks(parent_chunks: list[ParentChunk], output_dir: Path, id_norma: str) -> None:
    """
    Persiste los chunks en disco.

    Args:
        parent_chunks: Resultado de chunk_document().
        output_dir:    Carpeta de salida (se crea si no existe).
        id_norma:      Identificador del documento, usado como prefijo de archivo.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Parents (estructura jerárquica completa) ─────────────────────────
    parents_path = output_dir / f"{id_norma}_parents.json"
    with open(parents_path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in parent_chunks], f, ensure_ascii=False, indent=2)

    # ── Children aplanados (listos para el vector store) ────────────────
    # Formato: lista de {"content": "...", "metadata": {...}}
    # Compatible con LangChain Document y con la mayoría de vector stores.
    flat_children = [
        {"content": child.content, "metadata": child.metadata}
        for parent in parent_chunks
        for child in parent.children
    ]
    children_path = output_dir / f"{id_norma}_children.json"
    with open(children_path, "w", encoding="utf-8") as f:
        json.dump(flat_children, f, ensure_ascii=False, indent=2)

    log.info(
        "  Guardado: %d parents, %d children → %s",
        len(parent_chunks), len(flat_children), output_dir,
    )


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def process_corpus(input_dir: Path, output_dir: Path) -> None:
    """
    Procesa todos los archivos .md en input_dir y guarda los chunks en output_dir.

    Estructura esperada de input_dir:
        data/leyes_limpias/
            ley_1523_2012.md
            ley_1234_2008.md
            ...

    Estructura generada en output_dir:
        data/chunks/
            Ley_1523_2012_parents.json
            Ley_1523_2012_children.json
            Ley_1234_2008_parents.json
            ...

    Args:
        input_dir:  Carpeta con los Markdown limpios.
        output_dir: Carpeta donde se escriben los JSON de chunks.
    """
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        log.warning("No se encontraron archivos .md en %s", input_dir)
        return

    log.info("Procesando %d documentos desde %s", len(md_files), input_dir)

    total_parents  = 0
    total_children = 0

    for md_path in md_files:
        log.info("→ %s", md_path.name)
        text = md_path.read_text(encoding="utf-8")

        parent_chunks = chunk_document(text, md_path)

        # id_norma viene de la metadata extraída del texto.
        # Si el regex no encontró número de ley, cae al stem del archivo.
        id_norma = parent_chunks[0].metadata["id_norma"] if parent_chunks else md_path.stem

        save_chunks(parent_chunks, output_dir, id_norma)

        n_parents  = len(parent_chunks)
        n_children = sum(len(p.children) for p in parent_chunks)
        total_parents  += n_parents
        total_children += n_children

        log.info("  %d parents | %d children", n_parents, n_children)

    log.info(
        "Corpus completo: %d documentos | %d parents | %d children",
        len(md_files), total_parents, total_children,
    )


if __name__ == "__main__":
    process_corpus(INPUT_DIR, OUTPUT_DIR)