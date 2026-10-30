# shellcheck shell=bash
echo "== Wersjonowany prefiks środowiska Pythona (#193, M0) =="
# shellcheck disable=SC2016 # $target rozwija się w uruchomionym bash -c
expect_ok "Prefiks TLJH jest dowiązaniem do wersjonowanego środowiska" bash -c '
  test -L /opt/tljh/user &&
    target=$(readlink -f /opt/tljh/user) &&
    [[ $target == /opt/wlb/envs/python-* && -d $target && -x $target/bin/python ]]
'
expect_ok "Python ładuje pakiety TLJH i analityczne z dowiązania" \
  /opt/tljh/user/bin/python -c 'import jupyterhub, jupyterlab, jupyter_app_launcher, numpy, pandas'
expect_ok "Conda działa w prefiksie TLJH" bash -c \
  '/opt/tljh/user/bin/conda list --prefix /opt/tljh/user --json >/dev/null'
expect_ok "Kernelspec Pythona widoczny po relokacji" bash -c \
  '/opt/tljh/user/bin/jupyter kernelspec list | grep -q python3'
