# Flavor wlb-histologia: pulpit + RStudio + stos histologii (LibreOffice Calc, jamovi) na GOTOWYM
# obrazie wlb-general. Warstwowy build (jak wlb-memory/wlb-radiologia): iso_url to zbudowany wcześniej
# wlb-general.qcow2 (disk_image=true), nakładamy role desktop + rstudio + histo_apps (ansible/histologia.yml),
# nie przebudowując OS/Python/R. Obraz bazowy zostaje lekki; tu lądują aplikacje GUI i runtime Flatpaka.
#
# Blok packer{}/required_plugins jest w packer/plugins.pkr.hcl; variable "base_image" oraz locals
# image_date/repo_root są WSPÓŁDZIELONE z pozostałymi szablonami w katalogu — nie powtarzamy.

# Pulpit + Calc + RStudio + jamovi-Flatpak (app + runtime org.freedesktop.Platform, ~2 GB) potrzebują
# więcej miejsca niż baza (30G) i niż sam pulpit wlb-memory (40G). FSL-owej skali nie ma (to nie neuro).
variable "histologia_disk_size" {
  type    = string
  default = "50G"
}

locals {
  image_name_his = "wlb-histologia"
  full_name_his  = "${local.image_name_his}-${var.image_version}-${local.image_date}"
}

source "qemu" "wlb_histologia" {
  iso_url = var.base_image
  # Obraz bazowy ma już własną sumę SHA-256 policzoną przy swoim buildzie (#12/#71) — tu nie weryfikujemy.
  iso_checksum = "none"
  disk_image   = true
  disk_size    = var.histologia_disk_size

  format           = "qcow2"
  disk_compression = false # kompresja zstd w shell-local (#71)
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  accelerator      = "kvm"
  cpus             = var.build_cpus
  memory           = var.build_memory
  qemuargs         = [["-cpu", "host"]]
  headless         = true

  # Seed NoCloud współdzielony z wlb-memory: tymczasowy "packer" w grupie wlb-platform-admins.
  cd_label = "cidata"
  cd_content = {
    "meta-data" = "instance-id: wlb-packer-histologia\nlocal-hostname: wlb-build\n"
    "user-data" = templatefile("${local.repo_root}/packer/cloud-init/user-data-memory.pkrtpl.yaml", {
      ssh_public_key = trimspace(file("${local.repo_root}/${var.ssh_private_key_file}.pub"))
    })
  }

  ssh_username         = "packer"
  ssh_private_key_file = "${local.repo_root}/${var.ssh_private_key_file}"
  ssh_timeout          = "20m"

  shutdown_command = "sudo sh -c 'rm -f /etc/sudoers.d/90-cloud-init-users; userdel -f -r packer; shutdown -P now'"

  output_directory = "${local.repo_root}/output/${local.full_name_his}"
  vm_name          = "${local.full_name_his}.qcow2"
}

build {
  name    = "wlb-histologia"
  sources = ["source.qemu.wlb_histologia"]

  provisioner "shell" {
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "ansible" {
    playbook_file    = "${local.repo_root}/ansible/histologia.yml"
    user             = "packer"
    use_proxy        = false
    ansible_env_vars = ["ANSIBLE_CONFIG=${local.repo_root}/ansible/ansible.cfg"]
    extra_arguments = [
      "--extra-vars", "wlb_image_name=${local.image_name_his} wlb_image_version=${var.image_version} wlb_image_date=${local.image_date}",
      "--extra-vars", "wlb_artifacts_dir=${local.repo_root}/build/artifacts/${local.full_name_his}",
    ]
  }

  provisioner "shell" {
    execute_command = "sudo bash '{{ .Path }}'"
    script          = "${local.repo_root}/packer/scripts/cleanup.sh"
  }

  # Równoległa kompresja zstd zamiast disk_compression (zlib, 1 wątek) — #71. Przed manifestem/checksumą,
  # by suma objęła skompresowany obraz. jamovi-runtime + RStudio dają sporą alokację, więc zysk wyraźny.
  post-processor "shell-local" {
    inline = [
      "set -e",
      "img=${local.repo_root}/output/${local.full_name_his}/${local.full_name_his}.qcow2",
      "m=$(nproc); if [ \"$m\" -gt 16 ]; then m=16; fi",
      "qemu-img convert -c -W -m \"$m\" -O qcow2 -o compression_type=zstd \"$img\" \"$img.zst\"",
      "mv -f \"$img.zst\" \"$img\"",
      "echo \"Kompresja zstd zakonczona (-m $m)\"",
    ]
  }

  post-processor "manifest" {
    output     = "${local.repo_root}/output/${local.full_name_his}/packer-manifest.json"
    strip_path = true
    custom_data = {
      image_version = var.image_version
      image_date    = local.image_date
      base_image    = var.base_image
      git_commit    = var.git_commit
      git_describe  = var.git_describe
      git_dirty     = var.git_dirty
      build_run     = var.build_run
    }
  }

  post-processor "checksum" {
    checksum_types = ["sha256"]
    output         = "${local.repo_root}/output/${local.full_name_his}/${local.full_name_his}.qcow2.{{ .ChecksumType }}"
  }
}
