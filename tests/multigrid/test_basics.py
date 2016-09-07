from firedrake import *
import pytest


def test_refine_interval():
    m = UnitIntervalMesh(10)

    mh = MeshHierarchy(m, 1)

    assert mh[1].num_cells() == 2 * mh[0].num_cells()


@pytest.mark.parallel(nprocs=2)
def test_refine_interval_parallel():
    m = UnitIntervalMesh(10)

    mh = MeshHierarchy(m, 1)

    assert mh[1].num_cells() < 2 * mh[0].num_cells()


@pytest.mark.xfail(reason="Not yet implemented")
def test_refine_quad_mesh():
    m = UnitSquareMesh(2, 2, quadrilateral=True)

    mh = MeshHierarchy(m, 1)    # noqa


@pytest.mark.xfail(reason="Not yet implemented")
def test_refine_cube_mesh():
    m = UnitCubeMesh(2, 2, 2)

    mh = MeshHierarchy(m, 1)    # noqa


def test_refine_square_ncell():
    m = UnitSquareMesh(1, 1)

    mh = MeshHierarchy(m, 1)

    assert mh[1].num_cells() == 4 * mh[0].num_cells()


@pytest.mark.parallel(nprocs=2)
def test_refine_square_ncell_parallel():
    m = UnitSquareMesh(1, 1)

    mh = MeshHierarchy(m, 1)

    # Should be fewer than 4 times the number of coarse cells due to
    # halo shrinking.
    assert mh[1].num_cells() < 4 * mh[0].num_cells()


@pytest.mark.parallel(nprocs=2)
def test_refining_overlapped_mesh_fails_parallel():
    m = UnitSquareMesh(4, 4)

    m.init()

    with pytest.raises(RuntimeError):
        MeshHierarchy(m, 1)


def test_function_hierarchy_warning():
    m = UnitSquareMesh(4, 4)

    mh = MeshHierarchy(m, 1)

    fsh = FunctionSpaceHierarchy(mh, 'DG', 1)

    fh = FunctionHierarchy(fsh)

    with pytest.raises(AttributeError):
        fh._function_space

    assert len(fh) == len(fsh)


if __name__ == "__main__":
    import os
    pytest.main(os.path.abspath(__file__))