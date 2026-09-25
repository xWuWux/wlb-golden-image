# Instalacja środowiska R dla WLB — uruchamiane przez Ansible (rola r_env) jako root.
#
#   Rscript install-r-env.R <katalog_env> <katalog_jdbc>
#
# renv.lock z pakietami  -> renv::restore (wersje zamrożone, odtwarzalne budowanie)
# renv.lock bez pakietów -> instalacja z hades-packages.txt i wygenerowanie
#                           renv.lock.generated do zatwierdzenia w Git (make freeze)

args <- commandArgs(trailingOnly = TRUE)
env_dir <- args[[1]]
jdbc_dir <- args[[2]]
lib <- .Library.site[[1]]
options(Ncpus = parallel::detectCores())
Sys.setenv(PKG_SYSREQS = "true")  # pak doinstaluje brakujące biblioteki systemowe przez apt

install.packages(c("renv", "pak"), lib = lib)

lock <- file.path(env_dir, "renv.lock")
locked <- file.exists(lock) && length(renv::lockfile_read(lock)$Packages) > 0

if (locked) {
  message("renv.lock zawiera pakiety -> renv::restore")
  renv::restore(lockfile = lock, library = lib, prompt = FALSE)
} else {
  message("renv.lock pusty -> instalacja z hades-packages.txt")
  lines <- trimws(sub("#.*$", "", readLines(file.path(env_dir, "hades-packages.txt"))))
  for (entry in strsplit(lines[nzchar(lines)], "[[:space:]]+")) {
    ok <- tryCatch({
      pak::pkg_install(entry[[1]], lib = lib, upgrade = FALSE, ask = FALSE)
      TRUE
    }, error = function(e) {
      message("  ", entry[[1]], ": ", conditionMessage(e))
      FALSE
    })
    if (!ok) {
      if (length(entry) < 2) stop("Nie udało się zainstalować ", entry[[1]])
      message("  -> próba z ", entry[[2]])
      pak::pkg_install(entry[[2]], lib = lib, upgrade = FALSE, ask = FALSE)
    }
  }
}

# Kernel R widoczny w JupyterLab (środowisko użytkowników TLJH)
IRkernel::installspec(user = FALSE, name = "ir", displayname = "R (HADES)",
                      prefix = "/opt/tljh/user")

# Sterownik JDBC PostgreSQL dla DatabaseConnector (warstwa Gold, OMOP CDM)
dir.create(jdbc_dir, recursive = TRUE, showWarnings = FALSE)
DatabaseConnector::downloadJdbcDrivers("postgresql", pathToDriver = jdbc_dir)

# Zamrożenie faktycznie zainstalowanych wersji
project <- tempfile("wlb-renv-")
dir.create(project)
renv::snapshot(project = project, library = lib, type = "all", prompt = FALSE, force = TRUE,
               lockfile = file.path(env_dir, "renv.lock.generated"))
message("Zapisano ", file.path(env_dir, "renv.lock.generated"))
