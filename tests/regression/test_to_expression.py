from firedrake import *
import firedrake.expression as expression
import pytest
import numpy as np

def test_to_expression_1D():
    mesh = UnitIntervalMesh(5)
    V = FunctionSpace(mesh, "CG", 1)

    v1 = expression.to_expression(0.)
    v2 = expression.to_expression([0.])
    v3 = expression.to_expression("0.")
    v4 = expression.to_expression(["0."])

    f1 = interpolate(v1, V)
    f2 = interpolate(v2, V)
    f3 = interpolate(v3, V)
    f4 = interpolate(v4, V)

    assert (np.allclose(f1.dat.data_ro,f2.dat.data_ro) and
            np.allclose(f3.dat.data_ro,f4.dat.data_ro) and
            np.allclose(f1.dat.data_ro,f4.dat.data_ro))


def test_to_texpression_2D():
    mesh = UnitSquareMesh(3,3)
    V = VectorFunctionSpace(mesh, "CG", 1)

    v1 = expression.to_expression([1., 2.])
    v2 = expression.to_expression(["1.", 2.])
    v3 = expression.to_expression(["1.", "2."])

    f1 = interpolate(v1, V)
    f2 = interpolate(v2, V)
    f3 = interpolate(v3, V)

    assert (np.allclose(f1.dat.data_ro,f2.dat.data_ro) and
            np.allclose(f2.dat.data_ro,f3.dat.data_ro))


if __name__ == '__main__':
    import os
    pytest.main(os.path.abspath(__file__))
