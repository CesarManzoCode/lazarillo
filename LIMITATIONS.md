# Límites

Fuente única de lo que lazarillo no demuestra. Se amplía con los resultados negativos de cada K.

## De diseño

- **Base confiable.** Lean core, Mathlib y las dependencias de Mathlib se tratan como correctas. lazarillo no audita si una definición de Mathlib significa lo que el matemático quiere; solo reduce lo que un humano debe revisar a la frontera semántica del proyecto.
- **Comparator compara términos, no significados.** Que el enunciado del núcleo coincida con la referencia prueba que es el mismo término; si la referencia está mal escrita, el error pasa. La calidad de la referencia es responsabilidad de quien la escribe.
- **Mutaciones sobre la referencia.** Los errores sembrados se aplican a la copia de las definiciones en la referencia, no al código del proyecto, porque mutar una definición del proyecto suele romper las pruebas que la usan. La medición dice si lazarillo localiza una discrepancia entre proyecto y referencia; no dice cuántos errores de un proyecto real compilarían.
- **Huella.** La comparación propia de lazarillo usa `Expr.hash` sin `mdata`; dos términos distintos con la misma huella pasarían inadvertidos por lazarillo (no por Comparator).
- **Núcleo mínimo como conjunto.** El núcleo es la clausura de dependencias; no se intenta reescribir pruebas para usar menos lemas.
- **Explicaciones.** El texto lo escribe un modelo de 8 B parámetros cuantizado; su calidad no se mide mecánicamente y puede contener errores aunque cite metas reales. Solo se generan hasta la profundidad fijada por corpus.
- **Memoria.** El pico se mide con `/usr/bin/time -v` y con un muestreo cada 200 ms; un pico más corto que el intervalo puede escaparse del muestreo.
- **RH.** No se exporta su núcleo ni se corre Comparator sobre RH: el export completo pesa 61.6 GB. La fidelidad de RH se limita a axiomas, escaneo de fuentes y frontera semántica. RH no tiene licencia: se publican cifras, no texto derivado.
- **Constantes `quot`.** El grafo trata `Quot`, `Quot.mk`, `Quot.lift` y `Quot.ind` como un bloque (cada una depende de las otras tres) para que su cuenta coincida con la del exportador, que las escribe juntas. Si el objetivo alcanza una, el grafo cuenta las cuatro aunque no use las demás. Son de la base confiable, así que el núcleo no cambia.
- **Módulo de reto.** El módulo de reto se lee al final. Si redeclara un nombre del proyecto (en `pfr`, `PFRPalomar.Challenge` y `PFRPalomar.Solution` declaran ambos `Marton.pfr_conjecture`), el grafo y el núcleo usan la declaración del resto del proyecto, y la del reto solo entra en la auditoría como referencia aplanada.
- **Calibración.** El blueprint de `pfr` es un grafo humano; su divergencia con el grafo de declaraciones es esperable, así que precisión y exhaustividad miden coincidencia, no corrección.

## Resultados negativos

### K1

- **`fetch` sin reintentos.** Cuando falla una descarga, `fetch` corta ese corpus y sale con 1. En K1, con red intermitente, salió con 1 en dos verificaciones de cierre seguidas; una descarga de la toolchain v4.33.0-rc2 murió a los 343 MB. Hay que repetir `fetch` (es idempotente) hasta que salga con 0.
- **Exportadores ejercitados.** Solo se probaron dos caminos de exportación: `leanexport` de v4.37.0-rc1 (`pfr` y el fixture `mini`) y `lean4export` `v4.33.0-rc2` (`zeta23`). `lean4export` `v4.34.0-rc2` (`ns`) y `leanexport` de v4.35 (`zetalab`, `poincare`) quedan sin probar hasta K3.
- **Memoria no evaluada en K1.** La verificación de K1 comprueba que `timings.json` coincide con los logs crudos de `/usr/bin/time -v` y del muestreador, no que el pico quede bajo 16 GB. Que cabe en 16 GB se decide en K3.
- **con-leche sin criterio.** El tercer kernel se corre y su salida queda en `kernels.json`, pero ningún criterio de K1 lo evalúa.

### K2

- **Blueprint fuera del grafo (criterio 2).** Ocho nombres de Lean de etiquetas alcanzables desde `pfr` no están en la clausura de `PFR_conjecture`: `ProbabilityTheory.condEntropy_add_left`, `ProbabilityTheory.condEntropy_add_right`, `ProbabilityTheory.condEntropy_comp_ge`, `ProbabilityTheory.entropy_le_log_card`, `ProbabilityTheory.max_entropy_le_entropy_add`, `ProbabilityTheory.max_entropy_sub_mutualInfo_le_entropy_add`, `condRuzsaDist'_of_indep` y `rdist_le_sum_fibre`. Todos existen en el proyecto. Sus etiquetas listan varios nombres (p. ej. `\lean{rdist_of_indep_eq_sum_fibre, rdist_le_sum_fibre}`) y la prueba en Lean usa solo algunos: `rdist_of_indep_eq_sum_fibre` está en la clausura y los usuarios de `rdist_le_sum_fibre` en `PFR/` (`rdist_of_hom_le`, `single_fibres`) no. `calibration.json` los lista en `missing_in_graph`.
- **Precisión de aristas bajo el umbral.** Calibración de `PFR_conjecture` frente al blueprint: nodos 0.940 de precisión y 1.000 de exhaustividad; aristas 0.390 de precisión y 0.815 de exhaustividad. La precisión de aristas queda bajo el 0.50 de D10.
- **Metas de parámetros automáticos.** En `pfr`, 17 nodos del árbol (definiciones y estructuras como `ProbabilityTheory.entropy`, `rdist`, `ProbabilityTheory.IsUniform` y sus `mk`/`rec`/`casesOn`) tienen `by` en el código solo dentro de parámetros con valor automático, `(μ : Measure Ω := by volume_tac)`. Lean no ejecuta esa táctica al declarar, así que no hay `TacticInfo`: quedan con `tactic_proof` falso y `goals` vacío (comprobado con `lean/Goals.lean` en v4.37.0-rc1 sobre un archivo mínimo). La verificación de K2 exige metas a todo nodo cuyo texto contiene `by` y por eso los marca.
- **Mutaciones insuficientes para la tasa.** Con M1–M3, la frontera de `zeta23` tiene 14 apariciones de operadores (`IsNontrivialZero` 7, `zerosIn` 4, `N0simple` 3; `zeroMult` y `Ncount` ninguna) y la de `pfr` es vacía. Las 14 compilan, Comparator dice que las 14 cambian el enunciado y lazarillo marca las 14, pero D10 pide al menos 20, así que no se concluye una tasa de detección.
