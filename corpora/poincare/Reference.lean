import Mathlib

namespace DifferentialGeometry.Topology

universe u

theorem poincare_conjecture (M : Type u) [TopologicalSpace M] [ChartedSpace (EuclideanSpace ℝ (Fin 3)) M] [T2Space M] [CompactSpace M] [SimplyConnectedSpace M] : Nonempty (M ≃ₜ Metric.sphere (0 : EuclideanSpace ℝ (Fin 4)) 1) := by sorry

end DifferentialGeometry.Topology
