import sca_requirements as sca


def test_eksport_conda_i_pip(tmp_path, capsys):
    lock = tmp_path / "environment.lock.yml"
    lock.write_text(
        "name: x\ndependencies:\n"
        "  - pandas=2.2.3\n  - _libgcc_mutex=0.1\n  - python=3.12.4\n  - bez-wersji\n"
        "  - pip:\n      - inspectomop==0.2.3\n      - jupyterhub==5.2.1\n      - luzny>=1\n"
    )
    out = tmp_path / "sca/requirements.txt"
    assert sca.main([str(lock), str(out)]) == 0
    assert out.read_text().splitlines() == [
        "_libgcc_mutex==0.1",
        "inspectomop==0.2.3",
        "jupyterhub==5.2.1",
        "pandas==2.2.3",
        "python==3.12.4",
    ]
    assert "5 pakietów" in capsys.readouterr().out
