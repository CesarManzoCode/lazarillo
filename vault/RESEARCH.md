# Investigación — fuentes primarias con revisión fijada

Corte: 24 de noviembre de 2026. Etiquetas: **[observado]** = ejecutado en la máquina de César (Arch Linux x86-64, 16,009,695,232 bytes de RAM, 12 hilos) durante K0; **[documentado]** = dicho por la fuente primaria citada; **[hipótesis]** = no comprobado todavía. La investigación previa del laboratorio (`lab/research/00..99`) es contexto; lo que aquí contradice esa investigación está señalado en §9.

## 1. Corpus (commits fijados con `git ls-remote`, 24 nov 2026)

| Nombre | Repositorio | Commit | Subdirectorio | Toolchain (`lean-toolchain`) | Licencia | Teorema objetivo | Referencia |
|---|---|---|---|---|---|---|---|
| `pfr` | https://github.com/teorth/pfr | `1899ce8ed95fc310cce53d4c7ecfa2beb20ebec4` | `.` | `leanprover/lean4:v4.37.0-rc1` | Apache-2.0 | `Marton.pfr_conjecture` | módulo `PFRPalomar.Challenge` |
| `zeta23` | https://github.com/anthropics/formal-math (la URL `anthropics/zeta-23-lean` sirve el mismo repo, mismo HEAD) | `11b6c7e3c927df2658f513b6b68ea7f8929c62c5` | `zeta23` | `leanprover/lean4:v4.33.0-rc2` | Apache-2.0 | `two_thirds_simple_on_critical_line` | módulo `Challenge` (importa `ChallengeDeps`) |
| `zetalab` | https://github.com/teal-sea/zeta-lab | `a401821c9608526425f3d4cf7ff8e59bc37e1c79` | `lean` | `leanprover/lean4:v4.35.0-rc2` | MIT | `ZetaLean.Palomar.pub1_strong_closure` | módulo `Challenge` |
| `poincare` | https://github.com/qinz1yang/differential-geometry | `13c41a632efb8fbf93101c8a20f2a9214ab33240` | `.` | `leanprover/lean4:v4.35.0-rc3` | Apache-2.0 | `DifferentialGeometry.Topology.poincare_conjecture` | archivo propio `corpora/poincare/Reference.lean` (el repo no trae reto) |
| `rh` | https://github.com/leanprover-community/riemann-hypothesis | `4a5b4a2d2a5177a2b6cb876425f0cb4cb6b85061` | `.` (`srcDir = "src"`) | `leanprover/lean4:v4.37.0-rc1` | sin licencia («published without a license», espejo para chequeo) | `riemannHypothesis` | módulo `Challenge` |
| `ns` | https://github.com/openai/NavierStokesAndEuler | `f9e8bc5b38b6e212696e8a30e3e91517af887bbd` | `.` | `leanprover/lean4:v4.34.0-rc2` | Apache-2.0 | `NavierStokes.Comparator.navier_stokes_breakdown_R3` | módulo `ComparatorChallenges.NavierStokes` |

Detalles leídos en los archivos de cada commit [documentado]:

- `pfr`: `lakefile.toml` con `name = "PFR"`, `defaultTargets = ["PFR", "PFRPalomar"]`, dependencias `checkdecls`, `AddCombi` y `mathlib` en `c47f9ad906c5ec32a953f99911b446cd26dcc123`. `comparator.json` lista seis teoremas `Marton.*` con `permitted_axioms` = `propext`, `Quot.sound`, `Classical.choice`. `PFRPalomar/Solution.lean` prueba `pfr_conjecture` a partir de `PFR/`. El teorema de `PFR/Main.lean` es `PFR_conjecture`.
- Blueprint de `pfr`: fuentes en `blueprint/src/chapter/*.tex` (14 archivos: `100_percent.tex`, `approx_hom_pfr.tex`, `distance.tex`, `entropy.tex`, `entropy_pfr.tex`, `fibring.tex`, `further_improvement.tex`, `hom_pfr.tex`, `improved_exponent.tex`, `jensen.tex`, `main.tex`, `pfr.tex`, `torsion.tex`, `weak_pfr.tex`). Patrón: `\begin{theorem}[PFR]\label{pfr}` `\lean{PFR_conjecture}\leanok` … `\begin{proof}\uses{pfr_aux}\leanok`. Grafo publicado: https://teorth.github.io/pfr/blueprint/dep_graph_document.html.
- `zeta23`: `lakefile.toml` con bibliotecas `Zeta23`, `ChallengeDeps`, `Challenge`, `Solution`; Mathlib `51e6992efd06126df61a496bebf8f49482a4e129`. `ChallengeDeps.lean` (109 líneas, solo `import Mathlib`) define `IsNontrivialZero`, `zeroMult`, `zerosIn`, `Ncount`, `Ndist`, `N0star`, `N0simple` y variantes `…L` para Dirichlet. `Challenge.lean` enuncia 17 teoremas; `Solution.lean` cierra `two_thirds_simple_on_critical_line` con `Zeta23.thmB₀_mult`. `comparator.json` usa `enable_nanoda: true`.
- `zetalab`: `lean/lakefile.toml` con `name = "ZetaLean"`; Mathlib `065356127b1dc0016f66b7283ce0ce2c4055aa55`. `lean/Challenge.lean` define funciones propias (`aCoef`, `F1`, `clampI`, `massI`, `energyA`, `IsProfile`, `cStar`, …) y deja un `sorry` deliberado; `lean/comparator.json` lista tres teoremas `ZetaLean.Palomar.pub1_strong_closure*`.
- `poincare`: `lakefile.toml` `name = "DifferentialGeometry"`, versión 0.1.5; Mathlib `c55e6e786f49471c72fbddbec5415808896aec1e`. Enunciado en `DifferentialGeometry/Topology/ThreeManifold/Poincare.lean`, líneas 27–31, solo con nociones de Mathlib: `(M : Type u) [TopologicalSpace M] [ChartedSpace (EuclideanSpace ℝ (Fin 3)) M] [T2Space M] [CompactSpace M] [SimplyConnectedSpace M] : Nonempty (M ≃ₜ Metric.sphere (0 : EuclideanSpace ℝ (Fin 4)) 1)`.
- `rh`: `lakefile.toml` con `srcDir = "src"`, `moreLeanArgs = ["--tstack=400000"]`, `maxHeartbeats = 4000000`, Mathlib `31ce06eaadf4a200c0e1407c5f10953cf606b8f8`. README: «A full build takes hours, so you should use the cache: `lake exe cache get`»; `src/Challenge.lean` importa solo Mathlib; `comparator.json` lista cinco teoremas, empezando por `riemannHypothesis`, con kernels externos `leanchecker-paranoid` y `nanoda_bin`. La versión original de la prueba vive en la rama `original` y en `homeowmorphism/riemann-hypothesis-original` (`774b9e8022f50d20be861ecc9d609cfc26436a81`).
- `ns`: 2,659 archivos `.lean`, 624,698 líneas [observado con `git clone --depth 1`]; `lakefile.toml` con Mathlib `v4.34.0-rc2` y dependencia `Comparator` `v4.34.0-rc2`; retos en `ComparatorChallenges/NavierStokes.lean` (solo `import Mathlib`) y `ComparatorChallenges/NavierStokes.json`.

## 2. Toolchain de Lean y herramientas que trae

Fuente: toolchains instalados con elan 4.4.0 (`elan-init.sh` en `leanprover/elan@3cc76985a1becb3c03cd65c1c5007e6f186ae474`, sha256 `a620ff1641616222c8d37c54845492004bb84d6877cdbc944dd65c1aa685bf53`) en un directorio temporal de K0, ya borrado [observado].

| Toolchain | Commit de Lean | `leanexport` | `nanoda_bin`, `con-leche`, `con-ron`, `lean4lean`, `leanchecker-paranoid` |
|---|---|---|---|
| v4.33.0-rc2 | `d8b18978322de05a8f3dba51ef03cf5461676c17` | no | no |
| v4.34.0-rc2 | `6a10ac8c22beadecabdbb0919c2b50214762f91d` | no | no |
| v4.35.0-rc2 | `11acb17ec6b07a8f9e9173e6845197929540936b` | sí | sí |
| v4.37.0-rc1 | `0b77e12952ad39077d80d8bd6b66d601f225c321` | sí (lean4export 3.1.0, formato 3.1.0) | sí (`nanoda_bin 0.4.31`) |

- Referencia oficial: https://lean-lang.org/doc/reference/latest/External-Kernels/ (formato NDJSON 3.1.0: registros `in`/`il`/`ie`, declaraciones `axiom`, `def`, `opaque`, `thm`, `quot`, `inductive` con `types`/`ctors`/`recs`; cabecera `meta`) y https://lean-lang.org/doc/reference/latest/ValidatingProofs/ (el toolchain trae el kernel oficial, `con-leche`, `con-ron`, `lean4lean` y `nanoda`; `lean4checker --fresh`). Leídas el 24 nov 2026; la última versión listada en las notas es 4.37.0-rc1 (2026-11-18).
- Comparator independiente: https://github.com/leanprover/comparator README: «merged into core as of Lean release v4.35.0 in the form of `lake comparator` and the accompanying `lake check`».
- `lake help comparator` (v4.37.0-rc1) [observado]: `lake comparator [--config <FILE>] [--challenge-from-export <FILE>] [--solution-from-export <FILE>] [--paranoid] [--inadvisably-no-sandbox] [--json]`; configuración con `challenge_module`, `solution_module`, `theorem_names`, `permitted_axioms` (obligatorios), `definition_names`, `external_kernels`, `enable_nanoda`; códigos de salida 0 aceptado, 1 rechazado, 2 no pudo empezar; sandbox `bwrap` (`COMPARATOR_BWRAP`); el exportador es siempre el `leanexport` del toolchain.
- `lake help check` [observado]: `lake check [--from-export <FILE>] [--paranoid] [--inadvisably-no-sandbox] [--json]`; «replays the result through the kernel, erroring on any use of non-standard axioms»; requiere `lake-manifest.json`.
- `con-leche --help` [observado]: `con-leche [OPTIONS] [--] FILE.ndjson`, `--jobs=N`, `--olean --search-path=DIRS`, `--constant=NAME`; salida 0 aceptado, 1 rechazado, 2 declinado, 3 error.
- `nanoda_bin --help` [observado]: un único argumento, ruta a un JSON de configuración con `export_file_path`, `use_stdin`, `num_threads`, `stack_size_bytes`, `permitted_axioms`, `unpermitted_axiom_hard_error`, `unsafe_permit_all_axioms`, `nat_extension`, `string_extension`, `pp_*`, `print_success_message`. Fuente: https://github.com/ammkrn/nanoda_lib.
- lean4export independiente para toolchains sin `leanexport`: https://github.com/leanprover/lean4export, etiquetas `v4.33.0-rc2` = `9fb131bb100eb32ccf6836f14e4f8328d13b6792` y `v4.34.0-rc2` = `cacf989bd75f608700820f6afc595f32e7a99a4d`. Uso: `lake env <ruta>/lean4export <Módulo>+ [-- <decl>+]`; opciones `--export-unsafe`, `--export-mdata`.

## 3. Piloto de K0 [observado]

Proyecto Lean diminuto (un `def`, un lema por tácticas, un teorema objetivo, un `def` no usado), compilado con v4.37.0-rc1 y con v4.33.0-rc2:

1. `lake env leanexport Pilot -- target` exporta solo la clausura de `target` (1,277 registros; el `def` no usado queda fuera). Con v4.33.0-rc2, `lake env <lean4export v4.33.0-rc2> …` produce formato 3.1.0.
2. Sobre el export de la clausura: `nanoda_bin` imprime `Checked 1439 declarations with no typechecker errors` y sale 0; `con-leche` «accepted 1277 declarations» (cuenta bloques inductivos como uno); `lake check --from-export=…` sale 0 y su `--json` reporta `"Uses axioms: propext, Classical.choice, Quot.sound"`. El export hecho con v4.33.0-rc2 también lo aceptan los tres kernels de v4.37.0-rc1.
3. Quitando del export el registro de un lema del que depende el objetivo: nanoda sale 101 (`declaration target depends on myDouble_eq which was not found`), con-leche sale 1 (`unknown constant`), `lake check` sale 1.
4. `lake comparator --challenge-from-export --solution-from-export` exige que ambos exports contengan los axiomas permitidos y estas constantes, descubiertas una por una: `semiOutParam`, `autoParam`, `String.mk`, `eagerReduce`, `Nat.shiftRight`, `Nat.shiftLeft`, `Nat.xor`, `Nat.lor`, `Nat.land`, `Nat.gcd`. Con esas raíces añadidas al export del reto y de la solución, acepta (Lean default y nanoda `success`). Con un reto distinto (`3 * n`) rechaza con «Challenge and solution theorem statement do not match». Con una definición de la referencia distinta de la del proyecto rechaza con «Const does not match between challenge and target 'myDouble'»; con la misma definición escrita en otro módulo acepta.
5. Un archivo de referencia suelto se compila con `lake env lean Ref.lean -o Ref.olean` y se exporta añadiendo su carpeta a `LEAN_PATH` dentro de `lake env`. `lake check --from-export` y `lake comparator` funcionan desde un espacio de trabajo mínimo (`lakefile.toml` con una biblioteca vacía y `lake-manifest.json` generado por `lake build`).
6. `bwrap --dev-bind / / --unshare-net -- <cmd>` corta la red (curl falla), conserva el uid 1000 y deja correr `lake comparator` con su propio sandbox anidado.
7. Extractor por módulo: `Lean.readModuleData` sobre un `.olean` devuelve `ModuleData.constants`. `ConstantInfo.value?` no devolvió valor para teoremas en v4.37.0-rc1; el patrón `.thmInfo v => v.value` sí. Para archivos con `module` (sistema de módulos), el `.olean` principal trae las declaraciones como `axiom` sin cuerpo; hay que leer `readModuleDataParts #[f, f.server, f.private]` y tomar la última parte (`ModuleData.isModule` lo indica). `readModuleDataParts` e `isModule` existen en v4.33.0-rc2 y v4.34.0-rc2. El mismo script corre igual con v4.33.0-rc2.
8. Clausura desde los `.olean` frente al export: coincide salvo los recursores de cada bloque inductivo (50 de 1,439); al tratar un inductivo como dependiente de sus constructores, de todos los tipos de su bloque y de sus recursores, la cuenta es 1,439 = la de nanoda.
9. Memoria del extractor interpretado (`lake env lean --run`): 1.50 GB de RSS con un módulo, 2.0 GB con 682 módulos de `Init` (2.7 s); las regiones compactadas no se liberan dentro de un proceso.
10. Estados de meta: un script `lean --run` con `unsafe def main` y `enableInitializersExecution`, `Parser.parseHeader`, `processHeader`, `IO.processCommands` con `infoState.enabled := true`, recorre los `InfoTree`; cada `TacticInfo` da `goalsBefore` (impresos con `Meta.ppGoal`) y `ContextInfo.parentDecl?` da la declaración (`some myDouble_eq`). Funciona en v4.37.0-rc1 y v4.33.0-rc2.
11. Comparator con una «solución» que usa `sorry` (el export de la propia referencia): el reporte `--json` da `compare_statements: success` y `check_axioms: failure` («Illegal axiom detected: 'sorryAx'»); con una referencia mutada (`3 * n`) frente a la misma solución, `compare_statements: failure`. El paso de comparación se lee por separado del de axiomas.
12. `/usr/bin/time` es GNU Time 1.10; `-v` imprime `Maximum resident set size (kbytes)` y `Elapsed (wall clock) time`. `unshare -rn` y `bwrap` sin privilegios funcionan.
13. Observado en K1 (24 nov 2026):
    - En el fixture `mini`, la clausura desde los `.olean` daba 1,502 nodos y nanoda sobre el export solo del objetivo, 1,503. La diferencia es `Quot.ind`: `leanexport` escribe las cuatro constantes `quot` aunque el grafo solo alcance algunas. Con las aristas entre ellas, 1,503 = 1,503 en `mini` y 52,432 = 52,432 en `pfr`.
    - En `pfr`, `PFRPalomar.Challenge` y `PFRPalomar.Solution` declaran ambos `Marton.pfr_conjecture` (el primero con `sorry`). Si el reto se lee primero, el objetivo queda sin dependencias del proyecto.
    - `lean` de v4.37.0-rc1 rechaza un archivo fuera del directorio raíz (`input file … must be contained in root directory`; por defecto, el directorio actual). Con `--root=<carpeta del archivo>` compila y el módulo toma el nombre del archivo.

## 4. Modelo de lenguaje local

- llama.cpp: paquete Arch `extra/llama-cpp` 1.0.0-1 en el espejo (la base local de pacman aún dice 0.9.0), depende de `ggml` 1.0.0. Extraído sin instalar en un directorio temporal: `llama-completion --version` = `1.0.0-dev (build 12359, commit b1b770d90d)` [observado]. Banderas verificadas en `llama-completion --help`: `-m`, `-f`, `-n`, `-c`, `-t`, `-s/--seed`, `--temp`, `--top-k`, `--top-p`, `--min-p`, `-no-cnv`, `--no-display-prompt`, `--offline`, `--simple-io`, `--log-disable`, `-jf`, `--grammar-file`. Documentación: https://github.com/ggml-org/llama.cpp/blob/master/tools/completion/README.md.
- Modelo: `Qwen/Qwen3-8B-GGUF`, revisión `7c41481f57cb95916b40956ab2f0b139b296d974` (API de Hugging Face, `lastModified` 2025-05-21), licencia apache-2.0, archivo `Qwen3-8B-Q4_K_M.gguf`, 5,027,783,488 bytes, sha256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` [observado vía API]. Tarjeta del modelo: modo sin razonamiento con Temperature 0.7, TopP 0.8, TopK 20, MinP 0 [documentado]. No hay GGUF oficial de Qwen3.5/3.6/3.8 en el rango 7–14 B [documentado, colecciones de Qwen].
- [hipótesis] Pico de memoria de inferencia ≈ 5.0 GB de pesos + ~1.2 GB de caché KV a 8,192 tokens (36 capas × 8 cabezas KV × 128 × 2 × 2 bytes por token).

## 5. Fidelidad de Navier–Stokes

- arXiv 2610.08144 v1 (6 oct 2026), Bastounis, Circelli, Hansen, «Navier-Stokes lost in translation»: el Lema 8.6 del manuscrito corresponde, como lo más cercano, a `norm_derivativeWord_inverse_le` en `NavierStokes/SmoothFamilyTorusInverse.lean` líneas 1059–1080, commit `f9e8bc5`; el texto exige `m+4` derivadas y Lean `m+5` [documentado]. También señala `inverse_finiteJets`, `mixedJet_inverse_bound`, `exists_uniform_actual_pressure_flux_bound`, `exists_uniform_canonicalCutoffFlux_bound`, `canonicalCutoffFlux_bound`, `regularized_flux_Bound`.
- Nombre completo en Lean [observado en el clon]: `NavierStokes.SmoothFamilyTorusInverse.norm_derivativeWord_inverse_le` (único `namespace` del archivo; está en `section FiniteDimensional`).

## 6. Herramientas vecinas (posicionamiento)

| Herramienta | Fuente | Qué hace | Solapamiento con lazarillo |
|---|---|---|---|
| Lean Atlas / Lean Compass | https://github.com/NyxFoundation/lean-atlas (`3a81e194db0e6c41a2a8c5286f9e1b4962c3866a`), arXiv 2604.16347 | grafo tipo/valor, extrae nodos cuya semántica afecta a los objetivos | grafo y frontera; no re-chequea núcleo ni explica |
| lean-explain | https://github.com/koko1123/lean-explain (MIT) | explicaciones paso a paso ancladas en estados de meta vía REPL, recorre dependencias con `--depth` | explicación; sin doble kernel, sin Comparator, juez sin calibrar |
| LeanExplore | arXiv 2506.11085 | buscador de declaraciones | ninguno |
| Proof-Refactor | arXiv 2606.03743 | refactoriza pruebas generadas | ninguno |
| Lean Refactor | arXiv 2605.20244 | acorta pruebas con agente | ninguno |
| arXiv 2611.10961 | Saha et al., 7 nov 2026 | refina lemas preservando el blueprint | ninguno |
| arXiv 2509.17290 | Yu, Jia, 22 sep 2025 | ensayo sobre comprensión humana | motivación |
| ImProver | arXiv 2410.04753 | optimiza pruebas con LLM | ninguno |
| TheoremGraph / LeanGraph | arXiv 2606.25363 | extractor sobre el Environment | grafo |

## 7. Fondo AI for Math

- https://www.renaissancephilanthropy.org/ai-for-math-fund (leída el 24 nov 2026): seed grants «up to $100,000», «reviewed on a rolling basis», formulario https://renphil.fillout.com/t/6ZKnnnAPd9us. La convocatoria 2026 dice «Open to individuals and teams worldwide» y «All code, datasets, and research outputs must be open-access». Si ambas cosas aplican a los seed grants no está dicho en la página; el documento de reglas de seed grants (Google Docs) exige sesión y no se pudo leer.

## 8. Integración continua

- `actions/checkout` y `actions/setup-python`: etiqueta mayor más reciente `v7` en ambos (`git ls-remote --tags`, 24 nov 2026).

## 9. Correcciones a la investigación del laboratorio

- RH: la investigación dice Lean/Mathlib v4.33.1 (tutorial de agentspulse); el repositorio comunitario fija hoy `v4.37.0-rc1` y distribuye caché precompilada (`lake exe cache get`), así que no hace falta compilar 175,187 módulos.
- Poincaré: la investigación cita `differential-geometry` v0.1.3 con v4.33.1; el commit fijado es la versión 0.1.5 con v4.35.0-rc3.
- zeta-lab: la investigación no tenía toolchain; es v4.35.0-rc2 (su `formalization.yaml` dice v4.33.0-rc2, el manifiesto manda).
- Navier–Stokes: toolchain v4.34.0-rc2, Apache-2.0, 624,698 líneas.
- Herramientas marcadas [no encontrado] (lean-explain, LeanExplore, Proof-Refactor, Lean Refactor, ImProver, 2611.10961, 2509.17290): todas existen; ver §6.
- La cuenta de con-leche sobre RH (1,468,418) es de un export de terceros con otra toolchain; no es comparable con una corrida sobre el commit fijado.
