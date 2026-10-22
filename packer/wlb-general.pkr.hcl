# Blok packer{}/required_plugins jest w packer/plugins.pkr.hcl (wspólny dla katalogu).

locals {
  image_date = var.image_date != "" ? var.image_date : formatdate("YYYYMMDD", timestamp())
  full_name  = "${var.image_name}-${var.image_version}-${local.image_date}"
  repo_root  = abspath("${path.root}/..")
}

source "qemu" "wlb" {
  iso_url      = "https://cloud-images.ubuntu.com/releases/noble/${var.ubuntu_release}/ubuntu-24.04-server-cloudimg-amd64.img"
  iso_checksum = var.ubuntu_image_checksum
  disk_image   = true
  disk_size    = var.disk_size

  format           = "qcow2"
  disk_compression = true
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  accelerator      = "kvm"
  cpus             = var.build_cpus
  memory           = var.build_memory
  qemuargs         = [["-cpu", "host"]]
  headless         = true

  # Seed NoCloud dla maszyny budującej: tylko tymczasowy użytkownik "packer".
  cd_label = "cidata"
  cd_content = {
    "meta-data" = "instance-id: wlb-packer-build\nlocal-hostname: wlb-build\n"
    "user-data" = templatefile("${local.repo_root}/packer/cloud-init/user-data.pkrtpl.yaml", {
      ssh_public_key = trimspace(file("${local.repo_root}/${var.ssh_private_key_file}.pub"))
    })
  }

  ssh_username         = "packer"
  ssh_private_key_file = "${local.repo_root}/${var.ssh_private_key_file}"
  ssh_timeout          = "20m"

  # Usunięcie użytkownika budującego w tym samym poleceniu co wyłączenie — obraz wychodzi bez niego.
  shutdown_command = "sudo sh -c 'rm -f /etc/sudoers.d/90-cloud-init-users; userdel -f -r packer; shutdown -P now'"

  output_directory = "${local.repo_root}/output/${local.full_name}"
  vm_name          = "${local.full_name}.qcow2"
}

build {
  name    = "wlb"
  sources = ["source.qemu.wlb"]

  provisioner "shell" {
    # status 2 = zakończone z ostrzeżeniami, co nie blokuje budowania
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "ansible" {
    playbook_file    = "${local.repo_root}/ansible/site.yml"
    user             = "packer"
    use_proxy        = false
    ansible_env_vars = ["ANSIBLE_CONFIG=${local.repo_root}/ansible/ansible.cfg"]
    extra_arguments = [
      "--extra-vars", "wlb_image_name=${var.image_name} wlb_image_version=${var.image_version} wlb_image_date=${local.image_date}",
      "--extra-vars", "wlb_artifacts_dir=${local.repo_root}/build/artifacts/${local.full_name}",
      "--extra-vars", "wlb_git_commit=${var.git_commit} wlb_git_describe=${var.git_describe} wlb_git_dirty=${var.git_dirty} wlb_build_run=${var.build_run}",
    ]
  }

  provisioner "shell" {
    execute_command = "sudo bash '{{ .Path }}'"
    script          = "${local.repo_root}/packer/scripts/cleanup.sh"
  }

  post-processor "manifest" {
    output     = "${local.repo_root}/output/${local.full_name}/packer-manifest.json"
    strip_path = true
    custom_data = {
      image_version  = var.image_version
      image_date     = local.image_date
      ubuntu_release = var.ubuntu_release
      git_commit     = var.git_commit
      git_describe   = var.git_describe
      git_dirty      = var.git_dirty
      build_run      = var.build_run
    }
  }

  post-processor "checksum" {
    checksum_types = ["sha256"]
    output         = "${local.repo_root}/output/${local.full_name}/${local.full_name}.qcow2.{{ .ChecksumType }}"
  }
}
