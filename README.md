# lazarillo

Capa de comprensión, de código abierto, gratuita y local, para pruebas formales de Lean 4 generadas por IA.

Recibe un desarrollo de Lean 4 compilado y un teorema objetivo, y entrega:

- su **grafo** de dependencias, con aristas por sitio (tipo o valor) y nodos por tipo de declaración;
- su **núcleo**: las declaraciones del proyecto que lo sostienen, separadas de Lean core y Mathlib, re-chequeado por el kernel de Lean y por nanoda;
- una **auditoría** de fidelidad: axiomas, usos de `sorry`/`admit`/`axiom`/`native_decide`, la frontera semántica del enunciado y la comparación con un enunciado de referencia escrito solo con Lean core y Mathlib (Comparator);
- un **árbol de explicaciones** en inglés, un nodo por declaración del núcleo, anclado en los estados de meta del compilador y escrito por un modelo local.

Todo corre sin red durante el análisis y dentro de 16 GB de RAM. El contrato está en [`vault/CONTRACT.md`](vault/CONTRACT.md) y las fuentes en [`vault/RESEARCH.md`](vault/RESEARCH.md). Lo que no demuestra está en [`LIMITATIONS.md`](LIMITATIONS.md).

## Uso

```
python3 -m lazarillo fetch --model pfr
python3 -m lazarillo run work/corpora/pfr Marton.pfr_conjecture --out out/pfr --challenge-module PFRPalomar.Challenge
```

## Corpus de medición

`pfr` (con el blueprint de Tao), `zeta23`, `zetalab`, `poincare`, `rh` (prueba de la hipótesis de Riemann de Alpöge, 175,187 archivos) y `ns` (Navier–Stokes de OpenAI), cada uno en el commit y la versión de Lean que fija `corpora.toml`.

## Estado

| K | Contenido | Estado |
|---|---|---|
| K0 | Fundación: contrato, investigación, plan | cerrado |
| K1 | Grafo, núcleo, doble kernel y auditoría sobre `pfr` y `zeta23` | pendiente |
| K2 | Árbol de explicaciones, calibración con el blueprint y mutaciones | pendiente |
| K3 | Escala (RH, Navier–Stokes) y corpus restantes | pendiente |
| K4 | Publicación de resultados | pendiente |

## Resultados

Todavía no hay mediciones.

## Licencia

Apache-2.0, ver [`LICENSE`](LICENSE).
