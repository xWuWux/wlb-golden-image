import Lean
import Release
import ExportDecision

open Lean Elab Command in
run_cmd do
  -- Backtick elaboration also fails if a required theorem is removed or renamed.
  let required := #[``Release.matches_iff, ``Release.accepts_iff, ``Release.required_present,
                    ``Release.no_extra, ``Release.parent_identity, ``Release.reorder,
                    ``ExportDecision.commit_iff, ``ExportDecision.incomplete_stays_pending,
                    ``ExportDecision.retry_preserves_intent, ``ExportDecision.receipt_matches,
                    ``ExportDecision.delivered_stays_closed, ``ExportDecision.reachable_safe]
  let allowed := #[``propext, ``Quot.sound]
  let mut audited := #[]
  for (name, info) in (← getEnv).constants.toList do
    unless (`Release).isPrefixOf name || (`ExportDecision).isPrefixOf name do continue
    if info.isAxiom then throwError "Unexpected project axiom: {name}"
    unless info.isTheorem do continue
    audited := audited.push name
    let axioms ← collectAxioms name
    let unexpected := axioms.filter (!allowed.contains ·)
    unless unexpected.isEmpty do
      throwError "{name} depends on unapproved axioms: {unexpected}"
    if required.contains name then logInfo m!"{name}: {axioms}"
  for name in required do
    unless audited.contains name do throwError "Missing theorem: {name}"
