# semantic-document-extractor

[ Directorio de Origen: data/raw/*.docx ]
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 1: PARSING & ISOLATION (pypandoc + Regex)         │
│ ├─ Convierte DOCX a Markdown limpio (+pipe_tables)     │
│ ├─ Extrae fragmentos <table>...</table> con Regex      │
│ └─ Genera: data/processed/*.md  Y  /*_tables/*.html    │
└─────────────────┬──────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 2: DATA CLEANING (Regex Estructural)              │
│ ├─ Remueve ruido (headers, footers, saltos huérfanos)  │
└─────────────────┬──────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 3: CHUNKING JERÁRQUICO AVANZADO                   │
│ ├─ Parent Chunks: Segmentación por títulos (#, ##)     │
│ └─ Child Chunks (Laboratorio):                         │
│    └─ Comparación: Sliding Window vs Semantic Chunking │
└─────────────────┬──────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 4: CONTEXT ENRICHMENT (Metadatos en Cascada)      │
│ └─ Inyecta metadatos globales (Año, Norma, Entidad)    │
└─────────────────┬──────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 5: TABLE PARSING (Summary-Based Linkage)          │
│ ├─ LLM local procesa la tabla HTML -> Genera Resumen   │
│ └─ Vincula el Embedding del Resumen con la Tabla Real  │
└─────────────────┬──────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────┐
│ FASE 6: INDEXACIÓN LOCAL                               │
│ ├─ Carga Vectores a VDB Local (ChromaDB / FAISS)       │
│ └─ Configura Hard-Filtering lógico (Metadata WHERE)    │
└────────────────────────────────────────────────────────┘