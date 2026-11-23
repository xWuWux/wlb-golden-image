variable "image_name" {
  type    = string
  default = "wlb-general"
}

variable "image_version" {
  type        = string
  description = "Wersja semantyczna obrazu (np. 0.1.0)."
}

variable "image_date" {
  type        = string
  default     = ""
  description = "Data budowania YYYYMMDD; pusta = dzisiejsza."
}

# Przypięte wydanie Ubuntu 24.04 — zmiana tej wartości to świadoma aktualizacja bazy obrazu.
variable "ubuntu_release" {
  type    = string
  default = "release-20260911"
}

variable "ubuntu_image_checksum" {
  type    = string
  default = "sha256:612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354"
}

# Rozmiar dysku systemowego. Dysk roboczy (/workspace) jest osobnym wolumenem.
variable "disk_size" {
  type    = string
  default = "30G"
}

# Zasoby maszyny budującej — nie mają związku z kategorią VM (tę wyznacza flavor).
variable "build_cpus" {
  type    = number
  default = 4
}

variable "build_memory" {
  type    = number
  default = 6144
}

variable "ssh_private_key_file" {
  type    = string
  default = "build/packer_ed25519"
}

# Target in-session E2E pulpitu (#277-A): katalog /run/wlb/e2e, okno myszy (zenity) i terminal
# klawiatury w sesji badacza. Włączane TYLKO dla buildów testowych CI (ci/integration.sh -var),
# domyślnie false — obraz produkcyjny badacza nie zawiera fixture E2E.
variable "wlb_enable_e2e_target" {
  type        = bool
  default     = false
  description = "Zainstaluj target in-session dla testów E2E (#277); tylko buildy testowe."
}

# Profil budowy rozdziela obraz produkcyjny od buildów testowych CI (#277-S3).
# Produkcja jest domyślna i NIE może włączyć fixture E2E, nawet jeśli ktoś poda
# -var wlb_enable_e2e_target=true. Profil testowy ustawia wyłącznie ci/integration.sh.
variable "wlb_build_profile" {
  type        = string
  default     = "production"
  description = "Profil budowy: production (obrazy badacza) albo test (tylko CI E2E)."

  validation {
    condition     = contains(["production", "test"], var.wlb_build_profile)
    error_message = "Nieprawidłowy profil budowy: dozwolone są 'production' i 'test'."
  }
}

locals {
  # Jawne false dla produkcji: nie polegamy na domyślnej wartości roli/group_vars.
  # Fixture E2E może powstać tylko wtedy, gdy build jawnie zadeklaruje profil testowy.
  wlb_e2e_target_enabled = var.wlb_build_profile == "test" ? var.wlb_enable_e2e_target : false
}

# Proweniencja: powiązanie obrazu z kodem (#12a). Puste = budowanie poza git/CI.
variable "git_commit" {
  type        = string
  default     = ""
  description = "Pełny SHA commita, z którego zbudowano obraz."
}

variable "git_describe" {
  type        = string
  default     = ""
  description = "git describe --tags --always --dirty w chwili budowania."
}

variable "git_dirty" {
  type        = string
  default     = ""
  description = "1, gdy drzewo robocze miało niezacommitowane zmiany; 0 gdy czyste."
}

variable "build_run" {
  type        = string
  default     = ""
  description = "Identyfikator przebiegu CI (GITHUB_RUN_ID) albo 'local'."
}
