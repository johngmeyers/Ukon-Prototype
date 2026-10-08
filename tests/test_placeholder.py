import coverage_readiness


def test_package_imports():
    assert coverage_readiness.__version__ == "0.1.0"
