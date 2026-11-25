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
- **Calibración.** El blueprint de `pfr` es un grafo humano; su divergencia con el grafo de declaraciones es esperable, así que precisión y exhaustividad miden coincidencia, no corrección.

## Resultados negativos

Todavía no hay mediciones.
