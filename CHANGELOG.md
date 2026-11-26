# Cambios

## Sin publicar

### K2 — Decisiones de César sobre los criterios (2026-11-25)

- **Criterio 2 (blueprint ⊆ grafo) exige solo las declaraciones del blueprint que están en la clausura de `PFR_conjecture` según un export independiente hecho con `leanexport`, como lo enuncia la idea.** Descartado: exigir todo `\lean{…}` de las etiquetas alcanzables desde `pfr`, o agregar al grafo aristas que el término no tiene. Por qué: ocho nombres del blueprint no los usa la prueba en Lean y tampoco están en el export que aceptan los kernels. Efecto medido: 103 de 111 nombres están en el export y los 103 están en el grafo; los ocho restantes siguen en `missing_in_graph`.
- **La precisión de aristas de la calibración se mide por alcanzabilidad: una arista del árbol cuenta si el blueprint llega de un extremo al otro pasando por etiquetas intermedias; el umbral de 0.50 se conserva.** Descartado: bajar el umbral o quitar el criterio. Por qué: la prueba en Lean cita un lema directamente donde el blueprint pasa por etiquetas intermedias, y la contracción de caminos crea atajos. Efecto medido: precisión por alcanzabilidad 0.879 (327 de 372); la directa, 0.390 (145 de 372), se publica al lado en `calibration.json` (`precision_direct`).
- **El criterio 17 (estados de meta) exige metas solo a las declaraciones con un bloque de tácticas propio, no a las que tienen `by` solo en parámetros automáticos.** Descartado: inventar metas para esos nodos. Por qué: Lean no ejecuta esa táctica al declarar, así que el compilador no da metas. Efecto medido: 17 nodos del árbol de `pfr` quedan fuera y 299 tienen un bloque de tácticas propio.
- **Mutaciones: se mantiene el mínimo de 20 que cambian el enunciado y se amplía el diseño con los operadores M4–M8 (`.re`↔`.im`, `∩`↔`∪`, `=`↔`≠`, `+`↔`-`, `*`↔`/`) y el enunciado del objetivo en la referencia como sitio, en `pfr` y `zeta23`.** Descartado: bajar el mínimo. Por qué: con M1–M3 sobre la frontera había 14, y `pfr` no tiene frontera. Efecto medido: 53 cambian el enunciado según Comparator (`zeta23` 38, `pfr` 15) y lazarillo detecta las 53, sin falsos positivos en los controles.

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
