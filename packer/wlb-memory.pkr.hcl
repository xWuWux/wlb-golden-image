# Flavor wlb-memory (#106): warstwa pulpitu GUI na GOTOWYM obrazie wlb-general.
# Build warstwowy — iso_url to zbudowany wcześniej wlb-general.qcow2 (disk_image=true), więc
# nakładamy tylko rolę desktop (ansible/desktop.yml), nie przebudowując OS/Python/R. Kompromis
# między audytowalnością/podpisywaniem jednego artefaktu (#12/#71) a czasem budowania.

# Blok packer{}/required_plugins jest w packer/plugins.pkr.hcl (wspólny dla katalogu).

# Ścieżka do gotowego obrazu bazowego wlb-general (.qcow2). Podawana przy budowaniu:
#   packer build -var image_version=0.1.0 -var base_image=output/wlb-general-0.1.0-YYYYMMDD/wlb-general-...qcow2 packer/
variable "base_image" {
  type = string
  # Placeholder tylko na potrzeby walidacji — przy budowaniu PODAĆ realną ścieżkę przez -var base_image.
  default     = "output/wlb-general.qcow2"
  description = "Ścieżka do zbudowanego obrazu wlb-general .qcow2 (warstwa bazowa)."
}

# Pulpit + aplikacje GUI potrzebują więcej miejsca niż baza (30G). PoC z samym XFCE zmieści się,
# docelowy flavor z jamovi/LabPlot (#108/#109) wymaga podbicia.
variable "memory_disk_size" {
  type    = string
  default = "40G"
}

# local.image_date i local.repo_root są współdzielone z packer/wlb-general.pkr.hcl (locals są
# globalne dla katalogu) — tu definiujemy tylko unikalne dla flavora wlb-memory.
locals {
  image_name_mem = "wlb-memory"
  full_name_mem  = "${local.image_name_mem}-${var.image_version}-${local.image_date}"
}

source "qemu" "wlb_memory" {
  iso_url = var.base_image
  # Obraz bazowy ma już własną sumę SHA-256 policzoną przy swoim buildzie (#12/#71) — tu nie weryfikujemy.
  iso_checksum = "none"
  disk_image   = true
  disk_size    = var.memory_disk_size

  format           = "qcow2"
  disk_compression = true
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  accelerator      = "kvm"
  cpus             = var.build_cpus
  memory           = var.build_memory
  qemuargs         = [["-cpu", "host"]]
  headless         = true

  # Seed NoCloud: tymczasowy "packer" w grupie wlb-platform-admins (zahartowany AllowGroups bazy).
  cd_label = "cidata"
  cd_content = {
    "meta-data" = "instance-id: wlb-packer-memory\nlocal-hostname: wlb-build\n"
    "user-data" = templatefile("${local.repo_root}/packer/cloud-init/user-data-memory.pkrtpl.yaml", {
      ssh_public_key = trimspace(file("${local.repo_root}/${var.ssh_private_key_file}.pub"))
    })
  }

  ssh_username         = "packer"
  ssh_private_key_file = "${local.repo_root}/${var.ssh_private_key_file}"
  ssh_timeout          = "20m"

  shutdown_command = "sudo sh -c 'rm -f /etc/sudoers.d/90-cloud-init-users; userdel -f -r packer; shutdown -P now'"

  output_directory = "${local.repo_root}/output/${local.full_name_mem}"
  vm_name          = "${local.full_name_mem}.qcow2"
}

build {
  name    = "wlb-memory"
  sources = ["source.qemu.wlb_memory"]

  provisioner "shell" {
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "ansible" {
    playbook_file    = "${local.repo_root}/ansible/desktop.yml"
    user             = "packer"
    use_proxy        = false
    ansible_env_vars = ["ANSIBLE_CONFIG=${local.repo_root}/ansible/ansible.cfg"]
    extra_arguments = [
      "--extra-vars", "wlb_image_name=${local.image_name_mem} wlb_image_version=${var.image_version} wlb_image_date=${local.image_date}",
      "--extra-vars", "wlb_artifacts_dir=${local.repo_root}/build/artifacts/${local.full_name_mem}",
    ]
  }

  provisioner "shell" {
    execute_command = "sudo bash '{{ .Path }}'"
    script          = "${local.repo_root}/packer/scripts/cleanup.sh"
  }

  post-processor "manifest" {
    output     = "${local.repo_root}/output/${local.full_name_mem}/packer-manifest.json"
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
    output         = "${local.repo_root}/output/${local.full_name_mem}/${local.full_name_mem}.qcow2.{{ .ChecksumType }}"
  }
}
