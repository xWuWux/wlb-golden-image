# Flavor wlb-radiologia (#135): pulpit + ciężki stos neuroobrazowania (FSL, FSLeyes, 3DSlicer)
# na GOTOWYM obrazie wlb-general. Warstwowy build (jak wlb-memory): nakłada role desktop + neuro_apps
# (ansible/radiologia.yml). Obraz bazowy zostaje lekki; tu lądują wszystkie duże pliki.
#
# UWAGA ROZMIAR: FSL (conda-based) to kilkadziesiąt GB — qcow2 radiologiczny będzie bardzo duży.
# radiologia_disk_size trzeba dobrać do realnej instalacji (patrz #135, #71 o storage).
#
# packer/base_image, build_cpus/memory, ssh_private_key_file, locals image_date/repo_root oraz
# packer{}/required_plugins są WSPÓŁDZIELONE z pozostałymi szablonami w katalogu — nie powtarzamy.

variable "radiologia_disk_size" {
  type    = string
  default = "80G"
}

locals {
  image_name_rad = "wlb-radiologia"
  full_name_rad  = "${local.image_name_rad}-${var.image_version}-${local.image_date}"
}

source "qemu" "wlb_radiologia" {
  iso_url      = var.base_image
  iso_checksum = "none" # obraz bazowy ma własną sumę z własnego buildu (#12/#71)
  disk_image   = true
  disk_size    = var.radiologia_disk_size

  format           = "qcow2"
  disk_compression = true
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
    "meta-data" = "instance-id: wlb-packer-radiologia\nlocal-hostname: wlb-build\n"
    "user-data" = templatefile("${local.repo_root}/packer/cloud-init/user-data-memory.pkrtpl.yaml", {
      ssh_public_key = trimspace(file("${local.repo_root}/${var.ssh_private_key_file}.pub"))
    })
  }

  ssh_username         = "packer"
  ssh_private_key_file = "${local.repo_root}/${var.ssh_private_key_file}"
  ssh_timeout          = "20m"

  shutdown_command = "sudo sh -c 'rm -f /etc/sudoers.d/90-cloud-init-users; userdel -f -r packer; shutdown -P now'"

  output_directory = "${local.repo_root}/output/${local.full_name_rad}"
  vm_name          = "${local.full_name_rad}.qcow2"
}

build {
  name    = "wlb-radiologia"
  sources = ["source.qemu.wlb_radiologia"]

  provisioner "shell" {
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "ansible" {
    playbook_file    = "${local.repo_root}/ansible/radiologia.yml"
    user             = "packer"
    use_proxy        = false
    ansible_env_vars = ["ANSIBLE_CONFIG=${local.repo_root}/ansible/ansible.cfg"]
    extra_arguments = [
      "--extra-vars", "wlb_image_name=${local.image_name_rad} wlb_image_version=${var.image_version} wlb_image_date=${local.image_date}",
      "--extra-vars", "wlb_artifacts_dir=${local.repo_root}/build/artifacts/${local.full_name_rad}",
    ]
  }

  provisioner "shell" {
    execute_command = "sudo bash '{{ .Path }}'"
    script          = "${local.repo_root}/packer/scripts/cleanup.sh"
  }

  post-processor "manifest" {
    output     = "${local.repo_root}/output/${local.full_name_rad}/packer-manifest.json"
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
    output         = "${local.repo_root}/output/${local.full_name_rad}/${local.full_name_rad}.qcow2.{{ .ChecksumType }}"
  }
}
