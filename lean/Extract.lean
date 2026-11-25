/-
Declarations of compiled Lean modules, read from their `.olean` files
(CONTRACT §2, §3; RESEARCH §3.7, §3.8).

  lean --run lean/Extract.lean <out.ndjson> <file.olean>...

Writes one JSON line per constant with `name`, `module`, `kind`, `internal`,
`type_deps`, `value_deps`, `hash_type` and `hash_value`. Files of the module
system (`ModuleData.isModule`) keep the bodies in the last part of
`readModuleDataParts #[f, f.server, f.private]`.
-/
import Lean

open Lean

/-- Components joined by `.` without escapes, numeric components in decimal. -/
def nameStr (n : Name) : String :=
  n.toString (escape := false)

/-- Removes every `mdata` node. -/
partial def stripMData (e : Expr) : Expr :=
  e.replace fun
    | .mdata _ b => some (stripMData b)
    | _ => none

/-- `Expr.hash` after removing `mdata`, as 16 lowercase hexadecimal digits. -/
def fingerprint (e : Expr) : String :=
  let ds := Nat.toDigits 16 (stripMData e).hash.toNat
  (List.replicate (16 - ds.length) '0' ++ ds).foldl String.push ""

/-- Components after the last `lib/lean` pair. -/
partial def afterLibLean : List String → Option (List String)
  | "lib" :: "lean" :: rest => some ((afterLibLean rest).getD rest)
  | _ :: rest => afterLibLean rest
  | [] => none

/-- `<…>/lib/lean/A/B.olean` ↦ `A.B`; a file outside `lib/lean` ↦ its stem. -/
def moduleOf (path : System.FilePath) : String :=
  let comps := path.components
  let rel := (afterLibLean comps).getD [comps.getLastD ""]
  String.intercalate "." (rel.dropLast ++ [path.fileStem.getD ""])

def kindOf : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "thm"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "ctor"
  | .recInfo _ => "rec"

/-- Value of a def, theorem or opaque (`ConstantInfo.value?` misses theorems, RESEARCH §3.7). -/
def valueOf? : ConstantInfo → Option Expr
  | .defnInfo v => some v.value
  | .thmInfo v => some v.value
  | .opaqueInfo v => some v.value
  | _ => none

/-- The constants that `init_quot` declares together; the exporter writes all four. -/
def quotBlock : Array Name := #[``Quot, ``Quot.mk, ``Quot.lift, ``Quot.ind]

/-- Value edges of CONTRACT §2. An inductive depends on its constructors, on every
type of its block and on the recursors `T.rec` for each `T` of the block plus the
auxiliary `A.rec_i`, `i = 1..numNested`, named after the first type `A` of the block.
A `quot` constant depends on the other three of `quotBlock`. -/
def valueDeps (c : ConstantInfo) : Array Name :=
  match c with
  | .quotInfo _ => quotBlock.filter (· != c.name)
  | .inductInfo v =>
    let recs := v.all.map fun t => Name.str t "rec"
    let nested := match v.all with
      | t :: _ => (List.range v.numNested).map fun i => Name.str t s!"rec_{i + 1}"
      | [] => []
    (v.ctors ++ v.all ++ recs ++ nested).toArray
  | .ctorInfo v => #[v.induct]
  | .recInfo v =>
    v.rules.foldl (fun acc r => acc ++ r.rhs.getUsedConstants) #[c.name.getPrefix]
  | _ =>
    match valueOf? c with
    | some e => e.getUsedConstants
    | none => #[]

def namesJson (ns : Array Name) : Json :=
  Json.arr (ns.map fun n => Json.str (nameStr n))

def constLine (mod : String) (c : ConstantInfo) : String :=
  let hashValue := match valueOf? c with
    | some e => Json.str (fingerprint e)
    | none => Json.null
  (Json.mkObj [
    ("name", Json.str (nameStr c.name)),
    ("module", Json.str mod),
    ("kind", Json.str (kindOf c)),
    ("internal", Json.bool c.name.isInternal),
    ("type_deps", namesJson c.type.getUsedConstants),
    ("value_deps", namesJson (valueDeps c)),
    ("hash_type", Json.str (fingerprint c.type)),
    ("hash_value", hashValue)]).compress

def readConstants (f : String) : IO (Array ConstantInfo) := do
  let (d, _) ← readModuleData (System.FilePath.mk f)
  if d.isModule then
    let parts ← readModuleDataParts
      #[System.FilePath.mk f, System.FilePath.mk (f ++ ".server"), System.FilePath.mk (f ++ ".private")]
    match parts.back? with
    | some (p, _) => return p.constants
    | none => throw <| IO.userError s!"no module data parts for {f}"
  else
    return d.constants

def main (args : List String) : IO UInt32 := do
  match args with
  | out :: files@(_ :: _) =>
    IO.FS.withFile (System.FilePath.mk out) .write fun h => do
      for f in files do
        let mod := moduleOf (System.FilePath.mk f)
        for c in (← readConstants f) do
          h.putStrLn (constLine mod c)
    return 0
  | _ =>
    IO.eprintln "usage: lean --run lean/Extract.lean <out.ndjson> <file.olean>..."
    return 2
