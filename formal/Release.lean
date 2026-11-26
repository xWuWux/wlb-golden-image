namespace Release

/-- One entry in image-catalog.json, with its immediate parent. -/
structure Variant where
  name : String
  parent : Option String

/-- A decoded and uniquely keyed schema-1 record. -/
structure Image where
  name : String
  version : String
  digest : String
  baseDigest : Option String

/-- A trusted staging observation. None denotes a missing or ineligible file. -/
abbrev Observe := String → Option String

/-- Executable comparison of one declaration with one observed variant. -/
def matchesEntry (target : String) (observe : Observe) (v : Variant) (i : Image) : Bool :=
  i.name == v.name && i.version == target && observe v.name == some i.digest &&
    match v.parent with
    | none => i.baseDigest.isNone
    | some p => (observe p).any (fun d => i.baseDigest == some d)

/-- Both directions matter: a missing or an extra variant invalidates a candidate. -/
def accepts (target : String) (observe : Observe) (catalog : List Variant) (images : List Image) : Bool :=
  catalog.all (fun v => images.any (matchesEntry target observe v)) &&
    images.all (fun i => catalog.any (fun v => matchesEntry target observe v i))

/-- Declarative obligations, independent of the Boolean search through the lists. -/
def ValidEntry (target : String) (observe : Observe) (v : Variant) (i : Image) : Prop :=
  i.name = v.name ∧ i.version = target ∧ observe v.name = some i.digest ∧
    match v.parent with
    | none => i.baseDigest = none
    | some p => ∃ d, observe p = some d ∧ i.baseDigest = some d

theorem matches_iff (t : String) (o : Observe) (v : Variant) (i : Image) :
    matchesEntry t o v i = true ↔ ValidEntry t o v i := by
  cases hp : v.parent with
  | none => simp [matchesEntry, ValidEntry, hp, Bool.and_eq_true, and_assoc]
  | some p =>
    cases ho : o p <;> simp [matchesEntry, ValidEntry, hp, ho, Bool.and_eq_true, and_assoc]

/-- Soundness and completeness for every finite catalog, candidate, target and observation. -/
theorem accepts_iff (t : String) (o : Observe) (cs : List Variant) (imgs : List Image) :
    accepts t o cs imgs = true ↔
      (∀ v ∈ cs, ∃ i ∈ imgs, ValidEntry t o v i) ∧
      (∀ i ∈ imgs, ∃ v ∈ cs, ValidEntry t o v i) := by
  simp [accepts, List.all_eq_true, List.any_eq_true, matches_iff]

theorem required_present {t o cs imgs} (ok : accepts t o cs imgs = true) {v} (hv : v ∈ cs) :
    ∃ i ∈ imgs, i.name = v.name ∧ i.version = t ∧ o v.name = some i.digest := by
  obtain ⟨i, hi, h⟩ := ((accepts_iff ..).mp ok).1 v hv
  exact ⟨i, hi, h.1, h.2.1, h.2.2.1⟩

theorem no_extra {t o cs imgs} (ok : accepts t o cs imgs = true) {i} (hi : i ∈ imgs) :
    ∃ v ∈ cs, i.name = v.name := by
  obtain ⟨v, hv, h⟩ := ((accepts_iff ..).mp ok).2 i hi
  exact ⟨v, hv, h.1⟩

theorem parent_identity {t o cs imgs} (ok : accepts t o cs imgs = true) {v p}
    (hv : v ∈ cs) (hp : v.parent = some p) :
    ∃ i ∈ imgs, i.name = v.name ∧ ∃ d, o p = some d ∧ i.baseDigest = some d := by
  obtain ⟨i, hi, h⟩ := ((accepts_iff ..).mp ok).1 v hv
  exact ⟨i, hi, h.1, by simpa [hp] using h.2.2.2⟩

theorem reorder {t o cs cs' imgs imgs'} (hc : List.Perm cs cs') (hi : List.Perm imgs imgs') :
    accepts t o cs imgs = true ↔ accepts t o cs' imgs' = true := by
  simp only [accepts_iff, hc.mem_iff, hi.mem_iff]

end Release
