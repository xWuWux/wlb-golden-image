#!/usr/bin/env julia
# Instalacja wspólnego środowiska Julii i kernela IJulia dla JupyterHub (#111).
# Uruchamiane przez rolę julia_env w trakcie budowania obrazu (VM ma wtedy dostęp do sieci).
#
# Wywołanie:  julia install-julia-env.jl <katalog-projektu> <artefakt-manifest>
# Wymagane zmienne środowiskowe ustawia rola:
#   JULIA_DEPOT_PATH  = wspólny depot (tylko do odczytu dla badaczy w runtime)
#   JUPYTER           = /opt/tljh/user/bin/jupyter (kernel ląduje w prefiksie TLJH, jak IRkernel)
#
# Jeśli w projekcie jest już Manifest.toml — instalacja jest odtwarzana z niego (powtarzalność,
# jak lock ma pierwszeństwo w python_env/r_env). Bez niego rozwiązywana jest z Project.toml,
# a wygenerowany Manifest.toml kopiujemy do artefaktów budowania (jak renv.lock.generated).

import Pkg

project = abspath(ARGS[1])
manifest_out = length(ARGS) >= 2 ? ARGS[2] : ""

Pkg.activate(project)

# Świeży depot (JULIA_DEPOT_PATH wskazuje pusty katalog) nie ma żadnego rejestru pakietów.
# Bez niego resolve/instantiate po UUID pada: "expected package IJulia [...] to be registered".
# Dokładamy rejestr General przed rozwiązaniem (build ma dostęp do sieci). Idempotentnie.
if isempty(Pkg.Registry.reachable_registries())
    @info "Brak rejestru — dodaję General"
    Pkg.Registry.add("General")
end

if isfile(joinpath(project, "Manifest.toml"))
    @info "Manifest.toml obecny — odtwarzam środowisko (instantiate)"
    Pkg.instantiate()
else
    @info "Brak Manifest.toml — rozwiązuję z Project.toml (resolve)"
    Pkg.resolve()
    Pkg.instantiate()
end

Pkg.precompile()

# Kernel JupyterHub. env w kernel.json: wiodący ":" w JULIA_DEPOT_PATH dokłada prywatny depot
# badacza (~/.julia, zapisywalny) PRZED wspólnym (tylko do odczytu), a JULIA_PROJECT przypina
# kernel do wspólnego, zainstantiowanego środowiska.
using IJulia
IJulia.installkernel("Julia";
    env = Dict(
        "JULIA_DEPOT_PATH"  => ":" * ENV["JULIA_DEPOT_PATH"],
        "JULIA_PROJECT"     => project,
        "JULIA_NUM_THREADS" => "1",
    ),
)

# Zrzut dokładnych wersji do artefaktów budowania (powtarzalność).
if !isempty(manifest_out)
    cp(joinpath(project, "Manifest.toml"), manifest_out; force = true)
    @info "Manifest zapisany" manifest_out
end
