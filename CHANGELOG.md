# Cambios

## Sin publicar

- Fundación del proyecto: contrato (`vault/CONTRACT.md`), investigación con revisiones fijadas (`vault/RESEARCH.md`), licencia Apache-2.0, CI que corre `make check`.
- Decisiones de producto: Python con biblioteca estándar más dos scripts de Lean; grafo desde `.olean` por módulo; núcleo = clausura de dependencias del proyecto; doble kernel (Lean y nanoda) más con-leche; fidelidad con Comparator y frontera semántica; explicaciones con Qwen3-8B Q4_K_M y llama.cpp, sin red.
- Etapa `graph`: `lean/Extract.lean` lee los `.olean` por lotes y `lazarillo/graph.py` escribe `graph.ndjson` (clausura del objetivo) y `project_decls.txt`; fixture `tests/fixtures/mini`.
