# Cambios

## Sin publicar

### K1 — Grafo, núcleo, doble kernel y auditoría

- `python3 -m lazarillo fetch CORPUS...` instala elan, las toolchains, los corpus en su commit fijado, el exportador y el juez de verificación; con `--model` baja y verifica el modelo local. Es la única orden que usa red.
- `python3 -m lazarillo run PROJECT_DIR THEOREM --out OUT` corre en serie las etapas `graph`, `core`, `kernels` y `audit`, y mide el tiempo y la memoria de cada una en `timings.json`.
- Grafo: `graph.ndjson` con la clausura de dependencias del teorema, con aristas de tipo y de valor, y `project_decls.txt` con todas las declaraciones del proyecto. Se lee de los `.olean` por lotes. Su cuenta coincide con la de nanoda sobre un export independiente del teorema.
- Núcleo: `core.json` separa las declaraciones del proyecto de la base confiable (Lean core, Mathlib y sus dependencias). `core.ndjson` lo exporta, y el kernel de Lean (`lake check`), nanoda y con-leche lo re-chequean en `kernels.json`, también sobre una copia a la que le falta una declaración.
- Auditoría: `audit.json` con axiomas, usos de `sorry`/`admit`/`axiom`/`native_decide` en el grafo y en las fuentes, enunciado, frontera semántica, lemas del núcleo y la comparación con una referencia (el módulo de reto aplanado o un archivo dado) por huellas y por Comparator.
- `python3 -m lazarillo measure CORPUS` corre un corpus con sus parámetros de `corpora.toml` y escribe su `summary.json`.
- Medido en `pfr` y `zeta23`: corren sin red; ambos kernels aceptan el núcleo y rechazan el núcleo sin una declaración; Comparator acepta el núcleo frente a la referencia; los axiomas de `zeta23` son exactamente `propext`, `Classical.choice` y `Quot.sound`, sin `sorry`; dos corridas dan grafo y núcleo idénticos byte a byte.
- Correcciones antes del cierre: el grafo une las cuatro constantes `quot` (así su cuenta coincide con nanoda), lee al final el módulo de reto (que redeclara el teorema con `sorry`), y la referencia compila aunque esté fuera del proyecto.

### K0 — Fundación

- Fundación del proyecto: contrato (`vault/CONTRACT.md`), investigación con revisiones fijadas (`vault/RESEARCH.md`), licencia Apache-2.0, CI que corre `make check`.
- Decisiones de producto: Python con biblioteca estándar más dos scripts de Lean; grafo desde `.olean` por módulo; núcleo = clausura de dependencias del proyecto; doble kernel (Lean y nanoda) más con-leche; fidelidad con Comparator y frontera semántica; explicaciones con Qwen3-8B Q4_K_M y llama.cpp, sin red.
