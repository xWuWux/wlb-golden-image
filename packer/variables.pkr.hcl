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
