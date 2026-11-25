# Contrato de lazarillo

Fuente de verdad del producto. Los hechos y versiones citados están en `vault/RESEARCH.md`; aquí solo se citan por su sección (R§n). Lo marcado **[hipótesis]** no está comprobado y se mide en el K indicado.

## 1. Qué es

lazarillo recibe un desarrollo de Lean 4 ya compilado y el nombre de un teorema, y entrega, sin red y sin servicios de pago, dentro de 16 GB de RAM:

1. el **grafo** de dependencias del teorema, con aristas por sitio (tipo o valor) y nodos por tipo de declaración;
2. el **núcleo**: las declaraciones del proyecto que lo sostienen, separadas de la base confiable, exportado y re-chequeado por el kernel de Lean y por nanoda;
3. la **auditoría**: axiomas, usos de `sorry`/`admit`/`axiom`/`native_decide`, la frontera semántica del enunciado y la fidelidad frente a un enunciado de referencia escrito solo con Lean core y Mathlib (Comparator);
4. el **árbol de explicaciones**: un nodo por declaración del núcleo, con los estados de meta del compilador y un texto en inglés escrito por un modelo local.

No escribe pruebas ni las arregla; no juzga si una definición de Mathlib significa lo que el matemático quiere.

## 2. Definiciones

- **Base confiable**: los módulos del toolchain (`Init`, `Std`, `Lean`, `Lake`), el paquete `mathlib` y todo paquete listado en `.lake/packages/mathlib/lake-manifest.json` del corpus. Se trata como correcta y no se audita.
- **Proyecto**: todos los demás módulos compilados del corpus (paquete raíz y dependencias que no son base confiable).
- **Grafo del objetivo**: la clausura transitiva de dependencias del objetivo sobre todas las declaraciones (proyecto y base confiable). Aristas de tipo = constantes del tipo; aristas de valor = constantes del valor (def, thm, opaque), y además: un `inductive` depende de sus constructores, de todos los tipos de su bloque (`all`) y de sus recursores (`T.rec` por cada `T` del bloque y `T.rec_i` para `i = 1..numNested`); un constructor depende de su inductivo; un recursor depende de las constantes de sus reglas y de su inductivo.
- **Núcleo**: las declaraciones del proyecto que están en el grafo del objetivo. Es mínimo como conjunto: toda declaración del núcleo es mencionada por otra del grafo o es el objetivo, así que quitarla deja una constante desconocida y el kernel rechaza (criterio 9). No se hace reducción adicional (D04).
- **Archivo de núcleo** (`core.ndjson`): el export NDJSON 3.1.0 de la clausura de las raíces `R = [objetivo] + AXIOMAS_PERMITIDOS + RAICES_KERNEL` (base confiable incluida, porque el kernel parte de un entorno vacío). `AXIOMAS_PERMITIDOS = propext, Quot.sound, Classical.choice`. `RAICES_KERNEL = semiOutParam, autoParam, String.mk, eagerReduce, Nat.shiftRight, Nat.shiftLeft, Nat.xor, Nat.lor, Nat.land, Nat.gcd, Nat.add, Nat.sub, Nat.mul, Nat.div, Nat.mod, Nat.beq, Nat.ble, Nat.pow, Nat.log2` (R§3.4; las que no existan en el entorno se descartan y se listan en `dropped_roots`).
- **Enunciado**: las declaraciones del proyecto alcanzables desde el objetivo solo por aristas de tipo.
- **Frontera semántica**: desde las constantes del proyecto que aparecen en el tipo del objetivo, se siguen aristas de tipo siempre y aristas de valor solo desde `def`, `opaque`, `inductive`, `ctor` y `rec` (nunca desde `thm`); solo declaraciones del proyecto. Son las definiciones de las que depende el significado del enunciado.
- **Referencia**: un archivo `.lean` que importa solo módulos `Mathlib`, `Init`, `Std` o `Lean`, enuncia el objetivo con el mismo nombre y `sorry`, y contiene copias de las definiciones de la frontera. Si el corpus trae un módulo de reto, la referencia es ese módulo **aplanado**: se pega el texto de cada import del proyecto (recursivamente, en orden de dependencia, una vez cada uno) y se suben al inicio los imports de la base confiable.
- **Huella** de una declaración: `Expr.hash` del tipo y del valor tras quitar todos los nodos `mdata`, en hexadecimal de 16 dígitos.
- **Interno**: `Name.isInternal` verdadero (p. ej. `_proof_1`, `match_1`, `_private…`). El árbol colapsa los internos: si `d` usa un interno `i`, `d` usa las declaraciones no internas del proyecto alcanzables desde `i` pasando solo por internos.
- **Nombres**: en toda salida, componentes unidos por `.` sin escapes (`Name.toString (escape := false)`); componentes numéricos en decimal.

## 3. Arquitectura

- Python ≥ 3.12, solo biblioteca estándar, paquete `lazarillo/`; dos scripts de Lean interpretados con `lean --run`: `lean/Extract.lean` (grafo y huellas desde `.olean`) y `lean/Goals.lean` (estados de meta). Ningún kernel propio.
- Cada etapa corre como proceso hijo `/usr/bin/time -v -o OUT/logs/<etapa>.time python3 -m lazarillo stage <etapa> …`, con un muestreador que suma cada 200 ms el `VmRSS` de todo el árbol de procesos y escribe `OUT/logs/<etapa>.rss` (líneas `<ms> <bytes>`). Las etapas corren en serie y dentro de cada etapa los procesos de Lean también.
- Extracción por lotes: cada `lean --run lean/Extract.lean` lee como máximo 1,000 módulos o 2 GiB de `.olean` (lo que llegue antes) y escribe NDJSON; Python combina los lotes con nombres internados como enteros y listas de adyacencia en `array('I')`.
- Directorio de trabajo `$LAZARILLO_WORK`, por defecto `<repo>/work/` (ignorado por git):
  - `work/elan/` (`ELAN_HOME`), `work/tools/lean4export-<tag>/`, `work/judge/`, `work/models/`, `work/corpora/<nombre>/` (clon), `work/corpora/<nombre>.fetch.json`, `work/runs/<nombre>/`, `work/results/<nombre>/summary.json`, `work/results/summary.json`.
- **Toolchain de verificación** `leanprover/lean4:v4.37.0-rc1`: de él salen `lake check`, `lake comparator`, `nanoda_bin` y `con-leche` para todos los corpus. El export de cada corpus lo hace el exportador de su propia toolchain: `leanexport` si existe en `bin/` del toolchain; si no, `lean4export` compilado en la etiqueta igual a la versión (`v4.33.0-rc2`, `v4.34.0-rc2`) (R§2, R§3.1).
- **Juez**: `work/judge/` con `lean-toolchain` = toolchain de verificación, `lakefile.toml` (`name = "judge"`, `defaultTargets = ["Judge"]`, una `lean_lib` `Judge`), `Judge.lean` vacío y `lake-manifest.json` creado con `lake build`. `lake check` y `lake comparator` corren con ese directorio como `cwd` y con el `bin/` del toolchain de verificación al inicio de `PATH`.
- Todo proceso de Lean que lanza lazarillo corre con `ELAN_HOME=work/elan` y `work/elan/bin` al inicio de `PATH` (si ese elan no existe, con el `elan` del `PATH`); `lake`/`lean` de un corpus se resuelven por su `lean-toolchain` desde `PROJECT_DIR`.
- Sin red durante el análisis: `fetch` es la única orden que usa red. Los checkers corren `run` dentro de `bwrap --dev-bind / / --unshare-net --` (R§3.6).

## 4. Órdenes

```
python3 -m lazarillo fetch [--model] CORPUS...
python3 -m lazarillo run PROJECT_DIR THEOREM --out OUT [--challenge-module MODULE | --reference FILE]
        [--stages graph,core,kernels,audit,tree] [--depth N|all] [--explain-depth N]
python3 -m lazarillo measure CORPUS
python3 -m lazarillo mutate --run RUN_DIR --project PROJECT_DIR --out OUT
python3 -m lazarillo blueprint --tex-dir DIR --run RUN_DIR --root-label LABEL --root-decl DECL --out FILE
python3 -m lazarillo summarize
scripts/reproduce.sh
```

- `fetch`: instala elan en `work/elan` si falta (script `elan-init.sh` de `leanprover/elan@3cc76985a1becb3c03cd65c1c5007e6f186ae474`, sha256 verificado, `-y --no-modify-path --default-toolchain none`); instala la toolchain de cada corpus y la de verificación; clona cada corpus y hace `git checkout --detach <commit>`; en `PROJECT_DIR` corre `lake exe cache get` si el proyecto depende de `mathlib` y después `lake build` y `lake build <challenge_module>`; compila `lean4export` si hace falta; crea el juez; con `--model` baja `https://huggingface.co/<repo>/resolve/<revision>/<file>` a `work/models/` y verifica sha256. Escribe `work/corpora/<nombre>.fetch.json` con `project_dir`, `toolchain`, `lean_commit` y `exporter` (lista de argumentos). Es idempotente.
- `run`: etapas por defecto las cinco, en el orden `graph, core, kernels, audit, tree`; `--depth` por defecto 2, `--explain-depth` por defecto 1. Sale con 0 si produjo los archivos de las etapas pedidas, aunque un kernel rechace o Comparator no acepte: los veredictos son resultados.
- `measure`: lee `corpora.toml`, corre `run` sobre `work/corpora/<nombre>/<subdir>` con sus parámetros en `work/runs/<nombre>/` y escribe `work/results/<nombre>/summary.json`.
- `summary.json` de `measure`: `{"format":"lazarillo-summary/1","corpus","git","commit","toolchain","target","project_decls","core_decls","ratio","axioms","kernels","comparator","stages"}`; `kernels` = salidas de `kernels.json` (`lean`, `nanoda`, `con_leche`, `altered`) o `null`; `comparator` = `judgement` o `null`; `stages` = `timings.json["stages"]` sin rutas.
- Ubicaciones publicables: `mutate` escribe en `work/results/<corpus>/mutations/` y `blueprint` en `work/results/pfr/calibration.json` (así los invocan `scripts/reproduce.sh` y los checkers).
- `summarize`: reúne `work/results/*/summary.json`, `work/results/*/mutations/mutations.json` y `work/results/pfr/calibration.json` en `work/results/summary.json` = `{"format":"lazarillo-results/1","corpora":{<nombre>: summary},"mutations":{<nombre>: {"compiled","statement_changed_by_comparator","detected","detection_rate","out_of_frontier","controls","false_positives"}},"calibration": calibration}`; `detection_rate` = detectadas / cambiadas según Comparator (0.0 si ninguna cambió el enunciado; el conteo se publica al lado).
- `scripts/reproduce.sh`: único script que reproduce todas las mediciones publicadas: `fetch --model` de los seis corpus, `measure` de cada uno, `mutate` de `pfr` y `zeta23` (con `--run work/runs/<corpus>`), `blueprint` de `pfr`, `summarize`.

## 5. Archivos de salida de `run` (en `OUT/`)

Todo JSON se escribe con `sort_keys=True`, `ensure_ascii=False`, separadores `(",", ":")` en NDJSON y sangría 2 en JSON, terminando en salto de línea. `graph.ndjson`, `core.json` y `project_decls.txt` no contienen fechas, rutas absolutas ni tiempos: dos corridas con la misma versión producen bytes idénticos.

- `graph.ndjson` — una línea por nodo del grafo del objetivo, ordenadas por `name`: `{"hash_type","hash_value"(o null),"internal","kind","module","name","trusted","type_deps","value_deps"}`; `kind` ∈ `axiom, def, thm, opaque, quot, inductive, ctor, rec`; listas ordenadas y sin repetidos.
- `project_decls.txt` — todas las declaraciones del proyecto (no solo del grafo), ordenadas, una por línea.
- `core.json` — `{"format":"lazarillo-core/1","target","toolchain","project_decls","closure_decls","core_decls","ratio","core"}`; `ratio = core_decls / project_decls` redondeado a 6 decimales; `core` es la lista ordenada del núcleo.
- `core.ndjson` — el archivo de núcleo (etapa `kernels`).
- `kernels.json` — `{"format":"lazarillo-kernels/1","exporter","export_roots","dropped_roots","lean":{"exit","log"},"nanoda":{"exit","checked","log"},"con_leche":{"exit","log"},"altered":{"removed","lean_exit","nanoda_exit","con_leche_exit"}}`. `lean` es `lake check --from-export=core.ndjson` en el juez; nanoda con `permitted_axioms` = los tres, `unpermitted_axiom_hard_error: false`, `nat_extension` y `string_extension` verdaderos, `num_threads` = núcleos, `print_success_message: true`; `checked` es N de `Checked N declarations`. `altered` repite los tres kernels sobre una copia del export sin el registro de una declaración del núcleo distinta del objetivo (la primera en orden alfabético que el objetivo usa directamente).
- `audit.json` — `{"format":"lazarillo-audit/1","target","axioms","nonstandard_axioms","uses","source_scan","statement_decls","frontier","core_lemmas","reference","frontier_diff","statement_changed","comparator"}`:
  - `axioms`: nodos `axiom` del grafo, ordenados. `nonstandard_axioms`: los que no son los tres permitidos.
  - `uses`: `{"sorry": bool (sorryAx en el grafo), "native_decide": [axiomas del grafo cuyo nombre contiene "native" u "ofReduceBool"/"ofReduceNat"/"trustCompiler"], "project_axioms": [axiomas del proyecto en el grafo]}`.
  - `source_scan`: `{"files","sorry","admit","axiom","native_decide"}` contados en los archivos fuente del módulo del objetivo y de cada módulo del proyecto que importa transitivamente (líneas `import M`, también `public import` y `meta import`; el módulo `A.B` es el primer `A/B.lean` que exista bajo `PROJECT_DIR` o bajo un `srcDir` de su `lakefile.toml`, nunca dentro de `.lake/`; los módulos sin archivo así no se cuentan), tras quitar comentarios de bloque `/- … -/` (anidados) y de línea `--`; tokens con la expresión `(?<![\w.'])(sorry|admit|native_decide)(?![\w'])` y, para `axiom`, líneas que cumplen `^\s*((private|protected|noncomputable|unsafe)\s+)*axiom\s`.
  - `statement_decls`, `frontier`: listas ordenadas según §2. `core_lemmas`: `[{"name","module","kind"}]` de los teoremas no internos del núcleo, ordenados por nombre.
  - `reference`: `null` o `{"source","imports","export","module"}` con la ruta relativa a `OUT` de la referencia aplanada (`reference/Reference.lean`), sus imports, su export (`reference/reference.ndjson`, raíces `R`) y el módulo (`LazarilloRef`). La referencia se compila con la toolchain del corpus (`lake env lean … -o reference/LazarilloRef.olean`) y se extraen sus huellas con `lean/Extract.lean`.
  - `frontier_diff`: `{"changed","missing_in_reference","out_of_frontier_changed"}`: nombres de la frontera cuya huella difiere de la de la referencia, nombres de la frontera que la referencia no define, y declaraciones de la referencia que existen en el núcleo con otra huella pero están fuera de la frontera. `statement_changed` = `changed` o `missing_in_reference` no vacíos.
  - `comparator`: `null` si no hay referencia o no existe `core.ndjson`; si no, `{"exit","judgement","report"}` de `lake comparator --config reference/comparator.json --challenge-from-export=reference/reference.ndjson --solution-from-export=core.ndjson --json` en el juez, con `theorem_names = [objetivo]`, los tres axiomas y `external_kernels = {"nanoda": ["nanoda_bin"]}`; `report` es la ruta del JSON crudo guardado (`reference/comparator.report.json`).
- `tree.json` — `{"format":"lazarillo-tree/1","target","depth_limit","explain_depth","llm","nodes"}`; `llm` = `{"binary","version","model","model_sha256","params"}`; cada nodo: `{"name","kind","module","file","range","depth","parent","children","uses","statement","tactic_proof","goals","explanation"}`. Los nodos son las declaraciones no internas del núcleo alcanzables desde el objetivo por `uses` hasta `depth_limit` (BFS, profundidad 0 = objetivo), únicas. `uses` = dependencias directas no internas del proyecto tras colapsar internos, restringidas a nodos del árbol; `parent` = padre en el BFS (orden alfabético para desempatar); `children` = nodos cuyo `parent` es este. `file` relativo a `PROJECT_DIR` y `range = [línea_inicial, línea_final]` (de `findDeclarationRanges?`), `statement` = tipo impreso, `tactic_proof` verdadero si hubo algún `TacticInfo` de la declaración, `goals` = `[{"tactic","range","before"}]` con `before` la lista de metas impresas. `explanation` es texto si `depth ≤ explain_depth`, si no `null`.
- `tree.html` — un solo archivo sin recursos externos ni JavaScript: `<details>` anidados por `children`, anclas `id="n-<índice>"` y enlaces para `uses` a nodos ya mostrados.
- `timings.json` — `{"format":"lazarillo-timings/1","stages":{<etapa>:{"wall_s","peak_rss_bytes","time_max_rss_kb","log_time","log_rss"}}}`; `time_max_rss_kb` es el valor de `Maximum resident set size (kbytes)` de `log_time`, y `peak_rss_bytes = max(máximo de log_rss, time_max_rss_kb × 1024)`; `log_time` y `log_rss` son rutas relativas a `OUT`.
- `logs/` — salidas crudas: `<etapa>.time`, `<etapa>.rss` y la salida de cada herramienta externa.

## 6. Explicaciones

- Binario: `$LAZARILLO_LLAMA` o `llama-completion` en `PATH` (paquete Arch `llama-cpp` 1.0.0, R§4). Modelo `work/models/Qwen3-8B-Q4_K_M.gguf` con el sha256 de `corpora.toml`.
- Invocación por nodo: `llama-completion -m MODEL -f PROMPT -n 400 -c 8192 -t <núcleos> --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --seed 0 -no-cnv --no-display-prompt --offline --simple-io --log-disable`.
- Prompt en plantilla de chat de Qwen3 sin razonamiento: `<|im_start|>system\n…<|im_end|>\n<|im_start|>user\n…<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n`. El usuario recibe: nombre, tipo impreso, hasta tres estados de meta (primero, central, último) y nombre y tipo de hasta diez hijos. Se pide en inglés, a lo sumo 150 palabras, qué afirma la declaración y cómo procede la prueba, citando las metas.
- [hipótesis] El modelo de 5.0 GB cabe junto a una etapa de Lean dentro de 16 GB porque las etapas corren en serie; se mide en K2 y K3.

## 7. Mutaciones sembradas (`mutate`)

- Sobre `pfr` y `zeta23`. La mutación se aplica a la **referencia aplanada** del corpus, que siempre compila porque solo contiene definiciones y enunciados con `sorry`. Equivale a que el proyecto formalizó esa definición distinta de lo enunciado (D09).
- Sitios: (a) cada definición de la frontera presente en la referencia; (b) fuera de frontera: recorriendo en orden alfabético las declaraciones `def` no internas del núcleo, fuera de la frontera, cuyas dependencias son todas de la base confiable, las 10 primeras cuya copia mutada compila; se copia su texto fuente al final de la referencia dentro de `namespace <prefijo del nombre>` … `end <prefijo>` (para que conserve su nombre completo) y se muta la copia.
- Operadores, cada aparición es un candidato: `M1` literal numérico `k → k+1`; `M2` `<`↔`≤`, `>`↔`≥`; `M3` `∧`↔`∨`. Controles `C0`: insertar una línea de comentario dentro del cuerpo de cada definición de la frontera (no cambia el término).
- Cada candidato se compila (`lake env lean`); solo los que compilan forman el conjunto. Juez externo: `lake comparator --challenge-from-export=<referencia mutada> --solution-from-export=<referencia sin mutar>` en el juez; la verdad es `report.compare_statements.judgement` (`failure` = el enunciado cambió). Es válido porque Comparator ya aceptó la referencia sin mutar contra el núcleo real (criterio 8), y la igualdad estructural es transitiva.
- Auditoría de lazarillo por mutación: `frontier_diff` entre la referencia mutada y el núcleo; `statement_changed` y `classification` ∈ `statement_change`, `out_of_frontier`, `no_change`.
- Salidas en `OUT/`: `mutations.json` = `{"format":"lazarillo-mutations/1","corpus","target","candidates","compiled","mutations":[{"id","site","operator","in_frontier","dir","compile_exit","statement_changed","classification"}]}` y, por mutación, `OUT/<id>/Reference.lean`, `compile.log`, `comparator.json` (salida cruda de `--json`), `audit.json`.

## 8. Calibración con el blueprint (`blueprint`)

- Parser: sobre cada `.tex` de `--tex-dir` (recursivo, orden alfabético) sin comentarios `%` de TeX, un entorno de primer nivel `\begin{X}…\end{X}` con `\label{L}` es el nodo `L`; `\lean{a, b}` da sus nombres de Lean; `\uses{x, y}` dentro del entorno, o dentro de un entorno `proof` que aparezca después de él sin otro entorno con etiqueta en medio, da aristas `L → x`. Nombres y etiquetas sin espacios alrededor.
- `B` = etiquetas alcanzables desde `pfr` por `uses`. Criterio 2: todo nombre de Lean de `B` está en la clausura de `PFR_conjecture` dentro de `graph.ndjson`; se listan los faltantes.
- Proyección: `U` = declaraciones del proyecto que son nombre de Lean de alguna etiqueta. `T` = nodos de `tree.json` alcanzables desde `PFR_conjecture` por `uses`. `PT` = etiquetas de `T ∩ U`. `PB` = etiquetas de `B` con algún nombre de Lean en `project_decls.txt`. Nodos: precisión `|PT∩PB|/|PT|`, exhaustividad `|PT∩PB|/|PB|`. Aristas: `PE` = pares de etiquetas `(a,b)`, `a≠b`, con nodos `x∈a`, `y∈b` unidos por un camino de `uses` cuyos nodos interiores no están en `U`; `BE` = aristas `uses` del blueprint entre etiquetas de `PB`; precisión `|PE∩BE|/|PE|`, exhaustividad `|PE∩BE|/|BE|`.
- Salida `calibration.json`: `{"format":"lazarillo-calibration/1","root_label","root_decl","missing_in_graph","nodes":{"precision","recall"},"edges":{"precision","recall"}}`.

## 9. Corpus

`corpora.toml` (versionado, en la raíz) es exactamente esto; cada `[corpus.X]` lleva `challenge_module` o `reference`, nunca ambos:

```toml
[verification]
toolchain = "leanprover/lean4:v4.37.0-rc1"

[elan]
installer = "https://raw.githubusercontent.com/leanprover/elan/3cc76985a1becb3c03cd65c1c5007e6f186ae474/elan-init.sh"
sha256 = "a620ff1641616222c8d37c54845492004bb84d6877cdbc944dd65c1aa685bf53"

[lean4export]
git = "https://github.com/leanprover/lean4export"
"v4.33.0-rc2" = "9fb131bb100eb32ccf6836f14e4f8328d13b6792"
"v4.34.0-rc2" = "cacf989bd75f608700820f6afc595f32e7a99a4d"

[model]
repo = "Qwen/Qwen3-8B-GGUF"
revision = "7c41481f57cb95916b40956ab2f0b139b296d974"
file = "Qwen3-8B-Q4_K_M.gguf"
sha256 = "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
size = 5027783488

[corpus.pfr]
git = "https://github.com/teorth/pfr"
commit = "1899ce8ed95fc310cce53d4c7ecfa2beb20ebec4"
subdir = "."
toolchain = "leanprover/lean4:v4.37.0-rc1"
license = "Apache-2.0"
target = "Marton.pfr_conjecture"
challenge_module = "PFRPalomar.Challenge"
stages = ["graph", "core", "kernels", "audit", "tree"]
depth = "all"
explain_depth = 1

[corpus.zeta23]
git = "https://github.com/anthropics/formal-math"
commit = "11b6c7e3c927df2658f513b6b68ea7f8929c62c5"
subdir = "zeta23"
toolchain = "leanprover/lean4:v4.33.0-rc2"
license = "Apache-2.0"
target = "two_thirds_simple_on_critical_line"
challenge_module = "Challenge"
stages = ["graph", "core", "kernels", "audit", "tree"]
depth = 2
explain_depth = 1

[corpus.zetalab]
git = "https://github.com/teal-sea/zeta-lab"
commit = "a401821c9608526425f3d4cf7ff8e59bc37e1c79"
subdir = "lean"
toolchain = "leanprover/lean4:v4.35.0-rc2"
license = "MIT"
target = "ZetaLean.Palomar.pub1_strong_closure"
challenge_module = "Challenge"
stages = ["graph", "core", "kernels", "audit"]
depth = 2
explain_depth = 1

[corpus.poincare]
git = "https://github.com/qinz1yang/differential-geometry"
commit = "13c41a632efb8fbf93101c8a20f2a9214ab33240"
subdir = "."
toolchain = "leanprover/lean4:v4.35.0-rc3"
license = "Apache-2.0"
target = "DifferentialGeometry.Topology.poincare_conjecture"
reference = "corpora/poincare/Reference.lean"
stages = ["graph", "core", "kernels", "audit"]
depth = 2
explain_depth = 1

[corpus.ns]
git = "https://github.com/openai/NavierStokesAndEuler"
commit = "f9e8bc5b38b6e212696e8a30e3e91517af887bbd"
subdir = "."
toolchain = "leanprover/lean4:v4.34.0-rc2"
license = "Apache-2.0"
target = "NavierStokes.Comparator.navier_stokes_breakdown_R3"
challenge_module = "ComparatorChallenges.NavierStokes"
stages = ["graph", "core", "kernels", "audit", "tree"]
depth = 2
explain_depth = 2

[corpus.rh]
git = "https://github.com/leanprover-community/riemann-hypothesis"
commit = "4a5b4a2d2a5177a2b6cb876425f0cb4cb6b85061"
subdir = "."
toolchain = "leanprover/lean4:v4.37.0-rc1"
license = "none"
target = "riemannHypothesis"
challenge_module = "Challenge"
stages = ["graph", "core", "audit", "tree"]
depth = 2
explain_depth = 2
```

| Corpus | Etapas | `depth` / `explain_depth` | K |
|---|---|---|---|
| `pfr` | las cinco | `all` / 1 | K1, K2 |
| `zeta23` | las cinco | 2 / 1 | K1, K2 |
| `zetalab` | `graph,core,kernels,audit` | — | K3 |
| `poincare` | `graph,core,kernels,audit` (referencia `corpora/poincare/Reference.lean`) | — | K3 |
| `ns` | las cinco | 2 / 2 | K3 |
| `rh` | `graph,core,audit,tree` | 2 / 2 | K3 |

`corpora/poincare/Reference.lean`: `import Mathlib`, `namespace DifferentialGeometry.Topology`, `universe u`, el enunciado de R§1 con `:= by sorry`, `end DifferentialGeometry.Topology`.

## 10. Criterios de éxito y dónde se deciden

Numeración de `criterios` en la idea. Umbrales en D10.

| # | Criterio | Checker |
|---|---|---|
| 1 | Un comando produce grafo, núcleo, auditoría y árbol | K2 (`k2.command`) y fixture en K1 |
| 2 | Blueprint ⊆ grafo de `PFR_conjecture` | K2 |
| 3 | Precisión/exhaustividad del árbol frente al blueprint | K2 |
| 4 | Axiomas de zeta-23 exactamente los tres, sin sorry | K1 |
| 5 | RH: axiomas y escaneo coinciden con el escaneo público (0 usos) | K3 |
| 6 | Kernel de Lean re-chequea el núcleo | K1 (pfr, zeta23), K3 (zetalab, poincare) |
| 7 | nanoda acepta el export del núcleo | K1, K3 |
| 8 | Comparator contra la referencia | K1 (pfr, zeta23), K3 (zetalab, poincare, ns) |
| 9 | Núcleo alterado rechazado por ambos kernels | K1 |
| 10 | Cuenta del grafo = cuenta de un verificador independiente | K1 (nanoda sobre un export solo del objetivo) |
| 11 | Proyecto / núcleo / razón en corpus medianos | K3 |
| 12–15 | Mutaciones: conjunto, detección, fuera de frontera, falsos positivos | K2 |
| 16, 17 | Árbol: referencias válidas, estados de meta | K2 |
| 18–21 | RH y NS en 16 GB; tiempos registrados | K3 |
| 22 | NS: Lema 8.6 en el reporte de fidelidad | K3 |
| 23 | Sin red | K1, K2, K3 (todas las corridas en `bwrap --unshare-net`) |
| 24 | Modelo local, sin red ni claves | K2 |
| 25 | Reproducible byte a byte | K1, K3 |
| 26 | Licencia abierta y un script de reproducción | K4 |
| 27, 28 | No mecánicos: calidad del texto; a César le gusta | César, fuera de los checkers |

## 11. Conclusión permitida por medición

- Re-chequeo por kernel, nanoda, Comparator: **equivalente** al chequeo que hace la comunidad con las mismas herramientas; se concluye aceptado/rechazado, nada de velocidad.
- Cuenta del grafo contra nanoda: **equivalente** (mismo export, misma pregunta).
- Cuenta de RH contra la de con-leche publicada (1,468,418): **distinto** (otra toolchain y otro export); se reporta junto, sin conclusión.
- Calibración con el blueprint: **comparable** (misma pregunta, el blueprint es humano y el árbol es mecánico); se concluye solo precisión y exhaustividad.
- Memoria y tiempo en RH y NS: **distinto** frente a las cifras publicadas de otras máquinas (80 hilos, 500 GB); solo se concluye si cabe en 16 GB en esta máquina.

## 12. Decisiones cerradas

### Delegadas por la idea

**D01. Lenguajes.**
Decisión: Python ≥ 3.12 solo con biblioteca estándar para orquestación, grafo, auditoría, árbol, mutaciones y medición; Lean 4 interpretado (`lean --run`) solo para leer `.olean` y estados de meta.
Razón: la máquina no tiene pip ni pytest y sí Python 3.14; el piloto mostró que dos scripts de Lean de menos de 100 líneas corren sin cambios en v4.33 y v4.37 (R§3.7, R§3.10), sin compilar nada por toolchain.

**D02. Arquitectura y desarrollos que no caben en memoria.**
Decisión: tubería por etapas en procesos separados y en serie; extracción por módulo desde `.olean`, en lotes de a lo sumo 1,000 módulos o 2 GiB; el grafo en Python con nombres como enteros y `array('I')`; el export completo solo para el núcleo de los corpus medianos y NS.
Razón: un proceso de Lean no libera las regiones compactadas (2.0 GB con 682 módulos, R§3.9), así que los lotes acotan la memoria; RH tiene 175,187 módulos y un export de 61.6 GB, que no cabe.

**D03. Fuente del grafo.**
Decisión: `.olean` por módulo con `readModuleData`/`readModuleDataParts`, no el Environment importado completo ni el export de lean4export.
Razón: importar el Environment de RH entero no cabe en 16 GB [hipótesis de la investigación]; el export es casi 4 veces la RAM; los `.olean` dan las constantes post-elaboración por módulo y su clausura coincide con el export (1,439 = nanoda, R§3.8).

**D04. Núcleo mínimo.**
Decisión: clausura transitiva restringida al proyecto, sin reducción adicional; se audita con el kernel de Lean, nanoda y con-leche sobre el export, y quitando una declaración para ver que ambos kernels rechazan.
Razón: la clausura ya es mínima como conjunto de declaraciones (quitar cualquiera deja una constante desconocida, R§3.3); inlinar lemas es búsqueda costosa sin criterio que la pida.

**D05. Formato de salida y navegación.**
Decisión: JSON/NDJSON como fuente de verdad (§5) y un `tree.html` estático de un solo archivo con `<details>` anidados y enlaces.
Razón: JSON lo leen los checkers y la comunidad sin herramientas; un HTML sin JavaScript se abre sin red y se publica en cualquier sitio estático.

**D06. Modelo local.**
Decisión: `Qwen/Qwen3-8B-GGUF` Q4_K_M (5.03 GB, Apache-2.0) con `llama-completion` de llama.cpp 1.0.0, modo sin razonamiento, contexto 8,192, uno a la vez y después de las etapas de Lean.
Razón: es el GGUF oficial de licencia abierta más reciente en 7–14 B (R§4); 5.0 GB de pesos más ~1.2 GB de caché caben en 16 GB si no coinciden con Lean, y el paquete de Arch evita compilar.

**D07. Costo cero si falta cómputo.**
Decisión: nunca se usa cómputo de pago; si una etapa no cabe en 16 GB o no termina, se registra como resultado negativo medido (pico y punto de falla) y se ajustan solo perillas locales (tamaño de lote, profundidad); el CI gratuito solo corre tests.
Razón: restricción de costo cero de la idea; un resultado negativo medido es publicable, un cómputo prestado no es reproducible por la comunidad.

**D08. Orden de construcción.**
Decisión: K1 tubería mecánica (grafo, núcleo, kernels, auditoría) validada en `pfr` y `zeta23`; K2 árbol, modelo, calibración y mutaciones en esos dos; K3 escala y corpus restantes (`zetalab`, `poincare`, `ns`, `rh`); K4 publicación.
Razón: `pfr` (v4.37, `leanexport` incluido) y `zeta23` (v4.33, lean4export aparte) cubren los dos caminos de exportación y son los corpus de calibración y mutación; la escala solo tiene sentido con la tubería ya correcta.

**D09. Mutaciones y controles.**
Decisión: §7: mutaciones sobre la referencia aplanada (frontera de `zeta23`: `IsNontrivialZero`, `zeroMult`, `zerosIn`, `Ncount`, `N0simple`; fuera de frontera: copias de 10 definiciones hoja del núcleo por corpus); operadores M1–M3; controles C0 y toda mutación que Comparator acepta; juez Comparator.
Razón: mutar una definición dentro del proyecto casi siempre rompe las pruebas que la usan y el conjunto «que compila» quedaría vacío [hipótesis]; en la referencia siempre compila, y Comparator ya mostró que localiza la definición distinta (R§3.4). En `pfr` la frontera es vacía (su reto es solo Mathlib), así que aporta solo mutaciones fuera de frontera.

**D10. Umbrales y profundidad.**
Decisión: calibración: precisión de nodos > 0.70, exhaustividad de nodos > 0.90, precisión de aristas > 0.50, exhaustividad de aristas > 0.50. Mutaciones: detección > 0.95 con al menos 20 mutaciones que cambian el enunciado según Comparator; al menos 10 fuera de frontera y al menos 10 de control. Árbol: profundidad 2 con texto hasta 2 en RH y NS; `all` con texto hasta 1 en `pfr`; memoria: pico < 16 × 10⁹ bytes según `/usr/bin/time -v` y según el muestreador.
Razón: exhaustividad de nodos alta porque el criterio 2 ya exige que todo nodo del blueprint esté en el grafo; aristas más bajas porque el blueprint y el grafo de declaraciones divergen (arXiv 2604.24797) y la contracción de caminos crea atajos; detección casi total porque la huella y Comparator miran el mismo término; mínimos de 20/10/10 para que una tasa no salga de dos casos; profundidad 2 acota el texto del modelo a cientos de nodos.

**D11. Versiones de nanoda y lean4export; tercer kernel.**
Decisión: nanoda, `lake check` y Comparator del toolchain v4.37.0-rc1 para todos; exportador de la toolchain de cada corpus (`leanexport` desde v4.35, lean4export `v4.33.0-rc2` y `v4.34.0-rc2` para zeta23 y ns); tercer kernel: con-leche del mismo toolchain, reportado sin ser criterio.
Razón: el export 3.1.0 de v4.33.0-rc2 lo aceptan los kernels de v4.37 (R§3.2); con-leche viene incluido, tiene prueba de que no acepta `False` y costó 0.04 GiB en el piloto. Tenet exige .NET, que no está instalado.

**D12. Teorema objetivo por corpus.**
Decisión: los de R§1: `Marton.pfr_conjecture`, `two_thirds_simple_on_critical_line`, `ZetaLean.Palomar.pub1_strong_closure`, `DifferentialGeometry.Topology.poincare_conjecture`, `riemannHypothesis`, `NavierStokes.Comparator.navier_stokes_breakdown_R3`. La calibración con el blueprint usa el subárbol de `PFR_conjecture`.
Razón: son los teoremas que cada repo somete a Comparator (o el que su README nombra en Poincaré); en `pfr` el nodo del blueprint `pfr` enlaza `PFR_conjecture`, que está dentro del núcleo de `Marton.pfr_conjecture`.

**D13. Licencias, tamaños y versiones de los corpus.**
Decisión: los valores verificados en R§1 se fijan en `corpora.toml`; RH no tiene licencia, así que lazarillo lo descarga y mide pero no redistribuye ni su código ni sus salidas de texto, solo cifras.
Razón: verificado en los archivos de cada commit; publicar texto derivado de un código sin licencia no está permitido por defecto.

**D14. RH y NS en 16 GB.**
Decisión: RH se obtiene con `lake exe cache get` (sin compilar) y se procesan grafo, núcleo, auditoría y árbol; no se exporta su núcleo ni se corre Comparator en RH. NS se compila y se procesan las cinco etapas. Si algo no cabe, se reporta el pico medido y la etapa que falló.
Razón: el repo comunitario distribuye caché (R§1); el export de RH es 61.6 GB y Comparator lo cargaría entero; el criterio 8 se aplica a los corpus medianos y a NS.

**D15. Elegibilidad para seed grants desde México.**
Decisión: queda sin cerrar por falta de dato: la página pública no lo dice y el documento de reglas exige sesión (R§7); se anota en «Falta de César». El código se publica bajo Apache-2.0 de todos modos.
Razón: no se inventa una regla de elegibilidad; Apache-2.0 cumple el acceso abierto de la convocatoria 2026 si aplicara.

**D16. Herramientas vecinas y posicionamiento.**
Decisión: todas las herramientas antes no encontradas existen (R§6). lazarillo se posiciona como la única que junta núcleo re-chequeado por dos kernels, fidelidad con Comparator y frontera semántica medida con mutaciones, y escala a RH en 16 GB; la explicación anclada en metas se reconoce como compartida con lean-explain.
Razón: lean-explain ya explica pruebas con estados de meta, así que la explicación sola no es novedad; Lean Atlas reduce la revisión pero no re-chequea ni explica.

### Abiertas por el diseño

**D17. Identidad de nombres y huellas.**
Decisión: nombres sin escapes (§2) y huella = `Expr.hash` sin `mdata`.
Razón: el export usa componentes crudos; `mdata` no afecta al kernel y lean4export lo quita por defecto.

**D18. Medición de memoria.**
Decisión: `/usr/bin/time -v` por etapa más muestreo de la suma de `VmRSS` del árbol de procesos cada 200 ms; ambos deben quedar bajo el umbral.
Razón: `ru_maxrss` es el máximo de un proceso, no la suma de padre e hijos vivos a la vez; el muestreo cubre esa suma.

**D19. Sin red.**
Decisión: `fetch` es la única orden con red; el análisis se prueba dentro de `bwrap --dev-bind / / --unshare-net`.
Razón: verificado que corta la red sin cambiar el uid y que el sandbox anidado de Comparator funciona (R§3.6).

**D20. Tests.**
Decisión: `unittest` de la biblioteca estándar en `tests/test_*.py` (planos); los que necesitan Lean usan `tests/fixtures/mini/` (proyecto Lake sin dependencias, toolchain v4.37.0-rc1, objetivo `Mini.target` que usa un lema propio por tácticas, más un `def` no usado) y se saltan si no hay `elan`; el CI no instala Lean.
Razón: pytest no está instalado; el fixture ejercita grafo, núcleo y kernels en segundos.

**D21. Publicación de resultados.**
Decisión: los checkers de K1–K3 escriben las mediciones en `work/` (ignorado); K4 copia los `summary.json`, `mutations.json` y `calibration.json` a `results/` (versionado), escribe las tablas del README y publica.
Razón: los mini sprints no pueden correr mediciones largas, así que hace falta un K posterior a la última medición para versionarlas; en `work/` no hay riesgo de que un commit de mini sprint arrastre archivos a medio escribir.

**D22. Repositorio público.**
Decisión: licencia Apache-2.0; el remoto `origin` público lo crea César (K4 verifica que exista).
Razón: la idea exige código abierto; crear un repositorio público es una acción hacia fuera que solo César decide.

## 13. Contradicciones resueltas

- La idea pide «corpus medianos (Poincaré, zeta-lab, zeta-23)» con Poincaré de 4.7 M líneas, mayor que NS; se mantiene la clasificación de la idea.
- El criterio 8 dice «cada teorema objetivo»; RH queda fuera (D14) porque exige exportar 61.6 GB.
- El criterio 13 habla de mutaciones «que compilan» del proyecto; se aplican a la referencia (D09). Es la misma comparación (proyecto frente a lo enunciado) y está anotada en `LIMITATIONS.md`.
- La investigación fijaba versiones antiguas de RH y Poincaré; mandan los commits fijados (R§9).
