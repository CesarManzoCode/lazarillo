namespace Mini

structure Pair where
  fst : Nat
  snd : Nat

def helper (n : Nat) : Nat :=
  let p : Pair := ⟨n, n⟩
  p.fst + p.snd

theorem helper_eq (n : Nat) : helper n = 2 * n := by
  show n + n = 2 * n
  omega

theorem target (n : Nat) : helper n + helper n = 4 * n := by
  have h := helper_eq n
  omega

def unused (n : Nat) : Nat := n + 1

end Mini
