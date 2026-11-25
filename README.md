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
| K1 | Grafo, núcleo, doble kernel y auditoría sobre `pfr` y `zeta23` | Cerrada |
| K2 | Árbol de explicaciones, calibración con el blueprint y mutaciones | pendiente |
| K3 | Escala (RH, Navier–Stokes) y corpus restantes | pendiente |
| K4 | Publicación de resultados | pendiente |

## Resultados

### K1 (`pfr` y `zeta23`)

Verificación de cierre del 25 nov 2026, en esta máquina:

| Medición | `pfr` | `zeta23` |
|---|---|---|
| `fetch` termina con 0 | sí | sí |
| Corridas dentro de `bwrap --unshare-net`, sin claves, terminan con 0 | sí | sí |
| `lake check --from-export` acepta el núcleo | sí | sí |
| nanoda acepta el núcleo | sí | sí |
| Sin una declaración del núcleo, `lake check` y nanoda rechazan | sí | sí |
| Comparator acepta el núcleo frente a la referencia aplanada | sí | sí |
| Nodos del grafo = `Checked N` de nanoda sobre un export solo del objetivo | sí | sí |
| Núcleo contenido en el proyecto y en `core.ndjson`, cuentas cuadran | sí | sí |
| Escaneo de `sorry`/`admit`/`axiom`/`native_decide` = el de un escaneo independiente | sí | sí |
| `timings.json` = logs crudos de `/usr/bin/time -v` y del muestreador | sí | sí |
| `graph.ndjson`, `core.json` y `project_decls.txt` idénticos byte a byte en dos corridas | sí | sí |
| Axiomas exactamente `propext`, `Classical.choice`, `Quot.sound`, sin `sorry` | — | sí |

- En el fixture `tests/fixtures/mini`, `run` produce grafo, núcleo, export, kernels, auditoría y tiempos, y ambos kernels aceptan.
- 65 tests de `make check` pasan (94.9 s). La verificación de K1, con ambos corpus, tardó 4,286.7 s.
- Conteo del grafo frente a nanoda: 1,503 = 1,503 en `mini` y 52,432 = 52,432 en `pfr` (R§3.13).

Las cifras de núcleo, razón, tiempos por etapa y memoria se publican en K4.

## Licencia

Apache-2.0, ver [`LICENSE`](LICENSE).
