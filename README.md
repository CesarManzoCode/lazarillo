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
| K2 | Árbol de explicaciones, calibración con el blueprint y mutaciones | Cerrada |
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

### K2 (`pfr` y `zeta23`)

Verificación de cierre del 26 nov 2026, en esta máquina:

| Medición | Resultado |
|---|---|
| Un solo `run` sobre `pfr` termina con 0 y deja grafo, núcleo, auditoría, `tree.json` y `tree.html` | sí |
| Los nombres de Lean del blueprint de `pfr` que usa la prueba de `PFR_conjecture` están en su clausura del grafo | sí |
| `calibration.json` coincide con un cálculo independiente y supera los umbrales de D10 | sí |
| Todo nodo del árbol es del núcleo y del grafo, y sus referencias apuntan a nodos del árbol | sí |
| Toda declaración con bloque de tácticas propio trae al menos un estado de meta | sí |
| Árbol generado sin red ni claves con el modelo local de sha256 fijado; los nodos hasta `explain_depth` tienen texto | sí |
| Las mutaciones de `pfr` y `zeta23` compilan e importan solo Lean core y Mathlib | sí |
| Al menos 20 mutaciones cambian el enunciado según Comparator y lazarillo detecta más del 95 % | sí |
| Al menos 10 mutaciones fuera de la frontera, ninguna marcada como cambio de enunciado | sí |
| Al menos 10 mutaciones que Comparator acepta, ninguna marcada como cambio de enunciado | sí |

- 112 tests de `make check` pasan (124.7 s). La verificación de K2 tardó 111.2 s y la de K1 sobre la misma rama, 690.0 s.

Cifras medidas en K2 sobre `pfr` (`PFR_conjecture`) y `zeta23`, registradas en el contrato §7 y §8:

| Medición | Valor |
|---|---|
| Calibración, nodos: precisión / exhaustividad | 0.940 / 1.000 |
| Calibración, aristas: precisión por alcanzabilidad / directa / exhaustividad | 0.879 (327/372) / 0.390 (145/372) / 0.815 |
| Nombres de Lean del blueprint en el export independiente de `PFR_conjecture`, y de ellos en el grafo | 103 de 111, 103 de 103 |
| Nodos del árbol de `pfr` (`depth = all`) | 424 |
| Mutaciones `zeta23`: candidatas / compilan / cambian el enunciado | 72 / 54 / 38 |
| Mutaciones `pfr`: candidatas / compilan / cambian el enunciado | 20 / 17 / 15 |
| Mutaciones que cambian el enunciado detectadas por lazarillo | 53 de 53 |

Las cifras de núcleo, razón, tiempos por etapa y memoria se publican en K4.

## Licencia

Apache-2.0, ver [`LICENSE`](LICENSE).
