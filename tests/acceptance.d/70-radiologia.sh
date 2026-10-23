# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-radiologia sprawdza stos neuroobrazowania; na innych pomija.
if grep -qx "WLB_IMAGE_NAME=wlb-radiologia" /etc/wlb/image-release 2>/dev/null; then
  echo "== Stos neuroobrazowania (FSL, FSLeyes, 3DSlicer, #135) =="
  expect_ok "FSL zainstalowany (fslversion)" test -f /usr/local/fsl/etc/fslversion
  expect_ok "Środowisko FSL (profile.d/fsl.sh)" test -f /etc/profile.d/fsl.sh
  expect_ok "Narzędzie FSL obecne (fslmaths)" test -x /usr/local/fsl/share/fsl/bin/fslmaths
  expect_ok "FSLeyes obecny (w FSL)" test -x /usr/local/fsl/share/fsl/bin/fsleyes
  expect_ok "3DSlicer na PATH (Slicer)" test -x /usr/local/bin/Slicer
fi
