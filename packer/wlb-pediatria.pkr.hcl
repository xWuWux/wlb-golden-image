# Flavor wlb-pediatria (#271): pulpit + lokalny PostgreSQL 16 + klient DBeaver CE na GOTOWYM obrazie
# wlb-general. Warstwowy build (jak wlb-memory/radiologia): nakłada role desktop + postgres + dbeaver
# (ansible/pediatria.yml). Obraz bazowy zostaje lekki; tu lądują PG, DBeaver (Java) i sterownik JDBC.
#
# packer/base_image, build_cpus/memory, ssh_private_key_file, locals image_date/repo_root oraz
# packer{}/required_plugins są WSPÓŁDZIELONE z pozostałymi szablonami w katalogu — nie powtarzamy.

variable "pediatria_disk_size" {
  type    = string
  default = "40G"
}

locals {
  image_name_ped = "wlb-pediatria"
  full_name_ped  = "${local.image_name_ped}-${var.image_version}-${local.image_date}"
}

source "qemu" "wlb_pediatria" {
  iso_url      = var.base_image
  iso_checksum = "none" # obraz bazowy ma własną sumę z własnego buildu (#12/#71)
  disk_image   = true
  disk_size    = var.pediatria_disk_size

  format           = "qcow2"
  disk_compression = false # kompresja zstd w shell-local (#71)
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  accelerator      = "kvm"
  cpus             = var.build_cpus
  memory           = var.build_memory
  qemuargs         = [["-cpu", "host"]]
  headless         = true

  # Seed NoCloud współdzielony: tymczasowy "packer" w grupie wlb-platform-admins.
  cd_label = "cidata"
  cd_content = {
    "meta-data" = "instance-id: wlb-packer-pediatria\nlocal-hostname: wlb-build\n"
    "user-data" = templatefile("${local.repo_root}/packer/cloud-init/user-data-memory.pkrtpl.yaml", {
      ssh_public_key = trimspace(file("${local.repo_root}/${var.ssh_private_key_file}.pub"))
    })
  }

  ssh_username         = "packer"
  ssh_private_key_file = "${local.repo_root}/${var.ssh_private_key_file}"
  ssh_timeout          = "20m"

  shutdown_command = "sudo sh -c 'rm -f /etc/sudoers.d/90-cloud-init-users; userdel -f -r packer; shutdown -P now'"

  output_directory = "${local.repo_root}/output/${local.full_name_ped}"
  vm_name          = "${local.full_name_ped}.qcow2"
}

build {
  name    = "wlb-pediatria"
  sources = ["source.qemu.wlb_pediatria"]

  provisioner "shell" {
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "ansible" {
    playbook_file    = "${local.repo_root}/ansible/pediatria.yml"
    user             = "packer"
    use_proxy        = false
    ansible_env_vars = ["ANSIBLE_CONFIG=${local.repo_root}/ansible/ansible.cfg"]
    extra_arguments = [
      "--extra-vars", "wlb_image_name=${local.image_name_ped} wlb_image_version=${var.image_version} wlb_image_date=${local.image_date}",
      "--extra-vars", "wlb_artifacts_dir=${local.repo_root}/build/artifacts/${local.full_name_ped}",
      "--extra-vars", "wlb_enable_e2e_target=${var.wlb_enable_e2e_target}",
    ]
  }

  provisioner "shell" {
    execute_command = "sudo bash '{{ .Path }}'"
    script          = "${local.repo_root}/packer/scripts/cleanup.sh"
  }

  # Równoległa kompresja zstd zamiast disk_compression (zlib, 1 wątek) — #71. Przed manifestem/checksumą.
  post-processor "shell-local" {
    inline = [
      "set -e",
      "img=${local.repo_root}/output/${local.full_name_ped}/${local.full_name_ped}.qcow2",
      "m=$(nproc); if [ \"$m\" -gt 16 ]; then m=16; fi",
      "qemu-img convert -c -W -m \"$m\" -O qcow2 -o compression_type=zstd \"$img\" \"$img.zst\"",
      "mv -f \"$img.zst\" \"$img\"",
      "echo \"Kompresja zstd zakonczona (-m $m)\"",
    ]
  }

  post-processor "manifest" {
    output     = "${local.repo_root}/output/${local.full_name_ped}/packer-manifest.json"
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
    output         = "${local.repo_root}/output/${local.full_name_ped}/${local.full_name_ped}.qcow2.{{ .ChecksumType }}"
  }
}
