/- Reference contract for #20. The transition commits a decision and makes its delivery
   intent available in one step. Transport and the operator's current staging CLI are external. -/
namespace ExportDecision

/-- Immutable identity of a proposed delivery. Strings stand for validated opaque IDs. -/
structure Operation where
  requestId : String
  project : String
  manifestDigest : String
  purpose : String
  recipient : String
  channel : String
  deriving DecidableEq

/-- The authority layer supplies these facts for a single immutable operation.
    The controller's positive review includes the source-data exclusion and output check. -/
structure Evidence where
  leaderConsent : Option Operation
  controllerClearance : Option Operation

/-- One durable entry per request. Queued and delivered retain the original decision. -/
inductive State where
  | pending
  | queued (op : Operation)
  | delivered (op : Operation)

/-- A failed or repeated attempt leaves the durable entry unchanged. -/
def commit (state : State) (op : Operation) (e : Evidence) : State :=
  match state with
  | .pending =>
    if e.leaderConsent = some op ∧ e.controllerClearance = some op then .queued op else .pending
  | prior => prior

/-- A retry uses the stored operation, including its destination and idempotency key. -/
def nextDelivery : State → Option Operation
  | .queued op => some op
  | _ => none

def acknowledge (state : State) (receipt : Operation) : State :=
  match state with
  | .queued op => if receipt = op then .delivered op else state
  | prior => prior

theorem commit_iff (op : Operation) (e : Evidence) :
    commit .pending op e = .queued op ↔
      e.leaderConsent = some op ∧ e.controllerClearance = some op := by
  by_cases h : e.leaderConsent = some op ∧ e.controllerClearance = some op <;> simp [commit, h]

theorem incomplete_stays_pending (op : Operation) (e : Evidence)
    (h : ¬ (e.leaderConsent = some op ∧ e.controllerClearance = some op)) :
    commit .pending op e = .pending := by simp [commit, h]

theorem retry_preserves_intent (original proposed : Operation) (e : Evidence) :
    nextDelivery (commit (.queued original) proposed e) = some original := rfl

theorem receipt_matches (original receipt : Operation) :
    acknowledge (.queued original) receipt = .delivered original ↔ receipt = original := by
  by_cases h : receipt = original <;> simp [acknowledge, h]

theorem delivered_stays_closed (original proposed receipt : Operation) (e : Evidence) :
    nextDelivery (acknowledge (commit (.delivered original) proposed e) receipt) = none := rfl

/-- All reachable queued or delivered states have a matching earlier authorization.
    A crash or retry can leave the durable state unchanged. -/
inductive Reachable (authorized : Operation → Prop) : State → Prop where
  | start : Reachable authorized .pending
  | decide {s} (prior : Reachable authorized s) (op : Operation) (e : Evidence)
      (authentic : e.leaderConsent = some op → e.controllerClearance = some op → authorized op) :
      Reachable authorized (commit s op e)
  | confirm {s} (prior : Reachable authorized s) (receipt : Operation) :
      Reachable authorized (acknowledge s receipt)
  | recover {s} (prior : Reachable authorized s) : Reachable authorized s

def Safe (authorized : Operation → Prop) : State → Prop
  | .pending => True
  | .queued op | .delivered op => authorized op

theorem reachable_safe {authorized s} (h : Reachable authorized s) : Safe authorized s := by
  induction h with
  | start => trivial
  | @decide s _ op e ha ih =>
    cases s with
    | pending =>
      by_cases ok : e.leaderConsent = some op ∧ e.controllerClearance = some op
      · simpa [commit, ok, Safe] using ha ok.1 ok.2
      · simp [commit, ok, Safe]
    | queued _ => exact ih
    | delivered _ => exact ih
  | @confirm s _ receipt ih =>
    cases s with
    | queued op => by_cases ok : receipt = op <;> simpa [acknowledge, ok, Safe] using ih
    | pending => trivial
    | delivered _ => exact ih
  | recover _ ih => exact ih

end ExportDecision
