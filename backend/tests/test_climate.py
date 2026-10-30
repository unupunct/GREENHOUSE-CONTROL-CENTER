import math

from app.services.climate import dew_point_c, saturation_vapor_pressure_kpa, vpd_kpa


def test_svp_at_20c():
    assert math.isclose(saturation_vapor_pressure_kpa(20), 2.338, abs_tol=0.01)


def test_vpd_saturated_air_is_zero():
    assert abs(vpd_kpa(25, 100)) < 1e-9


def test_vpd_typical():
    # 25 C / 60 % RH -> about 1.27 kPa
    assert math.isclose(vpd_kpa(25, 60), 1.267, abs_tol=0.02)


def test_vpd_leaf_cooler_lowers_vpd():
    assert vpd_kpa(25, 60, leaf_temp_c=23) < vpd_kpa(25, 60)


def test_dew_point():
    assert math.isclose(dew_point_c(20, 100), 20, abs_tol=0.01)
    assert math.isclose(dew_point_c(25, 60), 16.7, abs_tol=0.2)
