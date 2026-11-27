import Lean.Data.Json
import Release

open Lean Release

deriving instance FromJson for Image
deriving instance FromJson for Variant

/-- A normalized test input. Python supplies independent observations of the staged files. -/
structure Input where
  target : String
  catalog : List Variant
  images : List Image
  files : List (String × String)
  deriving FromJson

def main : IO Unit := do
  let line ← (← IO.getStdin).getLine
  let input ← IO.ofExcept (Json.parse line >>= fromJson? (α := Input))
  IO.println (accepts input.target (fun name => input.files.lookup name) input.catalog input.images)
