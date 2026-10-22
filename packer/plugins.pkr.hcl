# Wspólna deklaracja wtyczek i wymaganej wersji Packera dla WSZYSTKICH szablonów w tym katalogu.
# Packer traktuje katalog jak jedną konfigurację HCL2 — blok packer{}/required_plugins może
# wystąpić tylko RAZ. Trzymamy go osobno, żeby kolejne flavory (wlb-general, wlb-memory, …)
# nie powielały go i nie powodowały kolizji "Duplicate required_plugin".
packer {
  required_version = ">= 1.10.0"
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1.1"
    }
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1.1"
    }
  }
}
