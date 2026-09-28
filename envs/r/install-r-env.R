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

# Zamrożenie faktycznie zainstalowanych wersji: lockfile w formacie renv budowany wprost
# z installed.packages(). renv::snapshot() poza projektem renv pomija bibliotekę site
# i zapisywał pusty lock (0 pakietów).
remote_fields <- c("RemoteType", "RemoteHost", "RemoteUsername", "RemoteRepo", "RemoteRef", "RemoteSha")
installed <- installed.packages(lib.loc = lib, fields = remote_fields)
records <- lapply(rownames(installed), function(pkg) {
  row <- installed[pkg, ]
  record <- list(Package = pkg, Version = unname(row[["Version"]]))
  if (identical(unname(row[["RemoteType"]]), "github")) {
    remote <- as.list(row[remote_fields])
    remote <- remote[!is.na(remote)]
    c(record, list(Source = "GitHub"), remote)
  } else {
    c(record, list(Source = "Repository", Repository = "CRAN"))
  }
})
names(records) <- rownames(installed)
if (length(records) == 0) stop("Biblioteka ", lib, " jest pusta — nie ma czego zamrozić")
lockfile <- list(
  R = list(Version = as.character(getRversion()),
           Repositories = list(list(Name = "CRAN", URL = unname(getOption("repos")[["CRAN"]])))),
  Packages = records[order(names(records))]
)
out <- file.path(env_dir, "renv.lock.generated")
jsonlite::write_json(lockfile, out, auto_unbox = TRUE, pretty = TRUE)
message("Zapisano ", out, " (", length(records), " pakietów)")
