/-
Goal states of one source file, read from its info trees (CONTRACT §2, §5; RESEARCH §3.10).

  lake env lean --run lean/Goals.lean <out.ndjson> <file.lean> [<module>]

Elaborates the file with `infoState.enabled := true` and writes one JSON line per
declaration the file adds, sorted by name: `name`, `range` (`[first, last]` lines of
`findDeclarationRanges?`, or null), `statement` (type printed with `ppExpr`) and
`tactics`, the `TacticInfo` nodes whose `ContextInfo.parentDecl?` is that declaration,
in info tree order: `{"tactic": syntax kind, "range": [first, last], "before": goals
printed with `ppGoal`}`. Only tactics whose syntax has an original position are kept.
`<module>` is the main module name (private names depend on it); by default the stem
of the file. Exits 1 if elaboration reported errors, after writing what it found.
-/
import Lean

open Lean Elab

/-- Components joined by `.` without escapes, numeric components in decimal. -/
def nameStr (n : Name) : String :=
  n.toString (escape := false)

/-- `A.B` ↦ ``A.B`` as a hierarchical name. -/
def parseModule (s : String) : Name :=
  (s.splitOn ".").foldl Name.mkStr .anonymous

structure Tactic where
  decl : Name
  kind : Name
  first : Nat
  last : Nat
  ctx : ContextInfo
  info : TacticInfo

/-- Every `TacticInfo` with an original position and a parent declaration. -/
def collectTactics (trees : Array InfoTree) : Array Tactic :=
  trees.foldl (init := #[]) fun acc t =>
    t.foldInfo (init := acc) fun ctx i acc =>
      match i, ctx.parentDecl? with
      | .ofTacticInfo ti, some d =>
        match ti.stx.getPos? (canonicalOnly := true), ti.stx.getTailPos? (canonicalOnly := true) with
        | some p, some q =>
          acc.push { decl := d, kind := ti.stx.getKind,
                     first := (ctx.fileMap.toPosition p).line,
                     last := (ctx.fileMap.toPosition q).line,
                     ctx, info := ti }
        | _, _ => acc
      | _, _ => acc

def rangeJson (first last : Nat) : Json :=
  Json.arr #[toJson first, toJson last]

def tacticJson (t : Tactic) : IO Json := do
  let ctx := { t.ctx with mctx := t.info.mctxBefore }
  let before ← t.info.goalsBefore.mapM fun g => do
    let f ← ctx.runMetaM {} (Meta.ppGoal g)
    return Json.str (toString f)
  return Json.mkObj [
    ("tactic", Json.str (nameStr t.kind)),
    ("range", rangeJson t.first t.last),
    ("before", Json.arr before.toArray)]

def declRange (env : Environment) (n : Name) (ctx : Core.Context) : IO Json := do
  let (r, _) ← Core.CoreM.toIO (findDeclarationRanges? n) ctx { env }
  match r with
  | some r => return rangeJson r.range.pos.line r.range.endPos.line
  | none => return Json.null

def statement (env : Environment) (c : ConstantInfo) (ctx : Core.Context) : IO String := do
  let (f, _) ← Core.CoreM.toIO (Meta.MetaM.run' (Meta.ppExpr c.type)) ctx { env }
  return toString f

unsafe def goalsMain (out file : String) (module? : Option String) : IO UInt32 := do
  enableInitializersExecution
  initSearchPath (← findSysroot)
  let input ← IO.FS.readFile file
  let inputCtx := Parser.mkInputContext input file
  let (header, parserState, messages) ← Parser.parseHeader inputCtx
  let mainModule := match module? with
    | some m => parseModule m
    | none => parseModule ((System.FilePath.mk file).fileStem.getD "Main")
  let opts := Options.empty.setBool `Elab.async false
  let (env, messages) ← processHeader header opts messages inputCtx (mainModule := mainModule)
  let env := env.setMainModule mainModule
  let cmdState := { Command.mkState env messages opts with infoState := { enabled := true } }
  let s ← IO.processCommands inputCtx parserState cmdState
  let env := s.commandState.env
  let msgs := s.commandState.messages
  for m in msgs.toList do
    if m.severity == .error then
      IO.eprintln (← m.toString)
  let tactics := collectTactics s.commandState.infoState.trees.toArray
  let coreCtx : Core.Context := { fileName := file, fileMap := inputCtx.fileMap, options := opts }
  let names := env.constants.foldStage2 (fun acc n _ => acc.push n) (#[] : Array Name)
  let names := names.qsort fun a b => nameStr a < nameStr b
  IO.FS.withFile (System.FilePath.mk out) .write fun h => do
    for n in names do
      let some c := env.find? n | continue
      let tacs ← (tactics.filter (·.decl == n)).mapM tacticJson
      h.putStrLn (Json.mkObj [
        ("name", Json.str (nameStr n)),
        ("range", ← declRange env n coreCtx),
        ("statement", Json.str (← statement env c coreCtx)),
        ("tactics", Json.arr tacs)]).compress
  return if msgs.hasErrors then 1 else 0

unsafe def main (args : List String) : IO UInt32 := do
  match args with
  | [out, file] => goalsMain out file none
  | [out, file, module] => goalsMain out file (some module)
  | _ =>
    IO.eprintln "usage: lean --run lean/Goals.lean <out.ndjson> <file.lean> [<module>]"
    return 2
