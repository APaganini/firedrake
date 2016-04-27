from __future__ import absolute_import
from firedrake import *
from firedrake import utils
from firedrake.petsc import PETSc
from impl import sscutils
import numpy

import ufl
from ufl.algorithms import map_integrands, MultiFunction
from impl.patches import get_cell_facet_patches, get_dof_patches


class ArgumentReplacer(MultiFunction):
    def __init__(self, test, trial):
        self.args = {0: test, 1: trial}
        super(ArgumentReplacer, self).__init__()

    expr = MultiFunction.reuse_if_untouched

    def argument(self, o):
        return self.args[o.number()]


class SubspaceCorrectionPrec(object):
    """Given a bilinear form, constructs a subspace correction preconditioner
    for it.  Currently, this is intended to approximate the solution
    of high-order Lagrange (eventually Bernstein as well)
    discretization by the solution of local problems on each vertex
    patch together with a global low-order discretization.

    :arg a:  A bilinear form defined in UFL
    :arg bcs: Optional strongly enforced boundary conditions
    """

    def __init__(self, a, bcs=None):
        self.a = a
        mesh = a.ufl_domain()
        self.mesh = mesh
        test, trial = a.arguments()
        V = test.function_space()
        assert V == trial.function_space()
        self.V = V
        if V.rank == 0:
            self.P1 = FunctionSpace(mesh, "CG", 1)
        elif V.rank == 1:
            assert len(V.shape) == 1
            self.P1 = VectorFunctionSpace(mesh, "CG", 1, dim=V.shape[0])
        else:
            raise NotImplementedError

        if bcs is None:
            self.bcs = ()
            bcs = numpy.zeros(0, dtype=numpy.int32)
        else:
            try:
                bcs = tuple(bcs)
            except TypeError:
                bcs = (bcs, )
            self.bcs = bcs
            bcs = numpy.unique(numpy.concatenate([bc.nodes for bc in bcs]))

        dof_section = V._dm.getDefaultSection()
        dm = mesh._plex
        cells, facets = get_cell_facet_patches(dm, mesh._cell_numbering)
        d, g, b = get_dof_patches(dm, dof_section,
                                  V.cell_node_map().values,
                                  bcs, cells, facets)
        self.cells = cells
        self.facets = facets
        self.dof_patches = d
        self.glob_patches = g
        self.bc_patches = b

    @utils.cached_property
    def P1_form(self):
        mapper = ArgumentReplacer(TestFunction(self.P1),
                                  TrialFunction(self.P1))
        return map_integrands.map_integrand_dags(mapper, self.a)

    @utils.cached_property
    def P1_bcs(self):
        bcs = []
        for bc in self.bcs:
            val = Function(self.P1)
            val.interpolate(as_ufl(bc.function_arg))
            bcs.append(DirichletBC(self.P1, val, bc.sub_domain, method=bc.method))
        return tuple(bcs)

    @utils.cached_property
    def P1_op(self):
        return assemble(self.P1_form, bcs=self.P1_bcs).M.handle

    @utils.cached_property
    def kernels(self):
        from firedrake.tsfc_interface import compile_form
        kernels = compile_form(self.a, "subspace_form")
        compiled_kernels = []
        for k in kernels:
            # Don't want to think about mixed yet
            assert k.indices == (0, 0)
            kinfo = k.kinfo
            assert kinfo.integral_type == "cell"
            assert not kinfo.oriented
            assert len(kinfo.coefficient_map) == 0

            kernel = kinfo.kernel
            compiled_kernels.append(kernel)
        return tuple(compiled_kernels)

    @utils.cached_property
    def matrix_callable(self):
        return sscutils.matrix_callable(self.kernels, self.V, self.mesh.coordinates)

    @utils.cached_property
    def matrices(self):
        mats = []
        dim = V.dof_dset.cdim
        coords = self.mesh.coordinates
        carg = coords.dat._data.ctypes.data
        cmap = coords.cell_node_map()._values.ctypes.data
        for i in range(len(self.dof_patches.offset) - 1):
            mat = PETSc.Mat().create(comm=PETSc.COMM_SELF)
            size = (self.glob_patches.offset[i+1] - self.glob_patches.offset[i])*dim
            mat.setSizes(((size, size), (size, size)),
                         bsize=dim)
            mat.setType(mat.Type.DENSE)
            mat.setOptionsPrefix("scp_")
            mat.setFromOptions()
            mat.setUp()
            marg = mat.handle
            mmap = self.dof_patches.value[self.dof_patches.offset[i]:].ctypes.data
            cells = self.cells.value[self.cells.offset[i]:].ctypes.data
            end = self.cells.offset[i+1] - self.cells.offset[i]
            self.matrix_callable(0, end, cells, marg, mmap, mmap, carg, cmap)
            mat.assemble()
            rows = self.bc_patches.value[self.bc_patches.offset[i]:self.bc_patches.offset[i+1]]
            rows = numpy.dstack([dim*rows + i for i in range(dim)]).flatten()
            mat.zeroRowsColumns(rows)
            mats.append(mat)
        return tuple(mats)

    def transfer_kernel(self, restriction=True):
        """Compile a kernel that will map between Pk and P1.

        :kwarg restriction: If True compute a restriction operator, if
             False, a prolongation operator.
        :returns: a PyOP2 kernel.

        The prolongation maps a solution in P1 into Pk using the natural
        embedding.  The restriction maps a residual in the dual of Pk into
        the dual of P1 (it is the dual of the prolongation), computed
        using linearity of the test function.
        """
        # Mapping of a residual in Pk into a residual in P1
        from coffee import base as coffee
        from tsfc.coffee import generate as generate_coffee, SCALAR_TYPE
        from tsfc.kernel_interface import prepare_coefficient, prepare_arguments
        from gem import gem, impero_utils as imp
        import ufl
        import numpy

        Pk = self.V
        P1 = self.P1
        # Pk should be at least the same size as P1
        assert Pk.fiat_element.space_dimension() >= P1.fiat_element.space_dimension()
        # In the general case we should compute this by doing:
        # numpy.linalg.solve(Pkmass, PkP1mass)
        matrix = numpy.dot(Pk.fiat_element.dual.to_riesz(P1.fiat_element.get_nodal_basis()),
                           P1.fiat_element.get_coeffs().T).T

        if restriction:
            Vout, Vin = P1, Pk
            weights = gem.Literal(matrix)
            name = "Pk_P1_mapper"
        else:
            # Prolongation
            Vout, Vin = Pk, P1
            weights = gem.Literal(matrix.T)
            name = "P1_Pk_mapper"

        funargs = []
        Pke = Vin.fiat_element
        P1e = Vout.fiat_element

        assert Vin.shape == Vout.shape

        shape = (P1e.space_dimension(), ) + Vout.shape + (Pke.space_dimension(), ) + Vin.shape

        outarg = coffee.Decl(SCALAR_TYPE, coffee.Symbol("A", rank=shape))
        i = gem.Index()
        j = gem.Index()
        pre = [i]
        post = [j]
        extra = []
        for _ in Vin.shape:
            extra.append(gem.Index())
        indices = pre + extra + post + extra

        indices = tuple(indices)
        outgem = [gem.Indexed(gem.Variable("A", shape), indices)]

        funargs.append(outarg)

        exprs = [gem.Indexed(weights, (i, j))]

        ir = imp.compile_gem(outgem, exprs, indices)

        body = generate_coffee(ir, {})
        function = coffee.FunDecl("void", name, funargs, body,
                                  pred=["static", "inline"])

        return op2.Kernel(function, name=function.name)

    @utils.cached_property
    def transfer_op(self):
        sp = op2.Sparsity((self.P1.dof_dset,
                           self.V.dof_dset),
                          (self.P1.cell_node_map(),
                           self.V.cell_node_map()),
                          "P1_Pk_mapper")
        mat = op2.Mat(sp, PETSc.ScalarType)
        matarg = mat(op2.WRITE, (self.P1.cell_node_map(self.P1_bcs)[op2.i[0]],
                                 self.V.cell_node_map(self.bcs)[op2.i[1]]))
        # HACK HACK HACK, this seems like it might be a pyop2 bug
        sh = matarg._block_shape
        assert len(sh) == 1 and len(sh[0]) == 1 and len(sh[0][0]) == 2
        a, b = sh[0][0]
        nsh = (((a*self.P1.dof_dset.cdim, b*self.V.dof_dset.cdim), ), )
        matarg._block_shape = nsh
        op2.par_loop(self.transfer_kernel(), self.mesh.cell_set,
                     matarg)
        mat.assemble()
        mat._force_evaluation()
        return mat.handle


class PatchPC(object):

    def setUp(self, pc):
        A, P = pc.getOperators()
        ctx = P.getPythonContext()
        ksp = PETSc.KSP().create()
        pfx = pc.getOptionsPrefix()
        ksp.setOptionsPrefix(pfx + "sub_")
        ksp.setType(ksp.Type.PREONLY)
        ksp.setFromOptions()
        self.ksp = ksp
        self.ctx = ctx

    def view(self, pc, viewer=None):
        if viewer is not None:
            comm = viewer.comm
        else:
            comm = pc.comm

        PETSc.Sys.Print("Vertex-patch preconditioner, all subsolves identical", comm=comm)
        self.ksp.view(viewer)

    def apply(self, pc, x, y):
        y.set(0)
        # Apply y <- PC(x)
        tmp_ys = []
        ctx = self.ctx
        bsize = ctx.V.dim
        for i, m in enumerate(ctx.matrices):
            self.ksp.reset()
            self.ksp.setOperators(m, m)
            ly, b = m.createVecs()
            ly.set(0)
            b.set(0)
            patch_dofs = ctx.glob_patches.value[ctx.glob_patches.offset[i]:ctx.glob_patches.offset[i+1]]
            bc_dofs = ctx.bc_patches.value[ctx.bc_patches.offset[i]:ctx.bc_patches.offset[i+1]]
            b.array.reshape(-1, bsize)[:] = x.array_r.reshape(-1, bsize)[patch_dofs]
            b.array.reshape(-1, bsize)[bc_dofs] = 0
            self.ksp.solve(b, ly)
            tmp_ys.append(ly)

        for i, ly in enumerate(tmp_ys):
            patch_dofs = ctx.glob_patches.value[ctx.glob_patches.offset[i]:ctx.glob_patches.offset[i+1]]
            y.array.reshape(-1, bsize)[patch_dofs] += ly.array_r.reshape(-1, bsize)[:]


class P1PC(object):

    def setUp(self, pc):
        self.pc = PETSc.PC().create()
        self.pc.setOptionsPrefix(pc.getOptionsPrefix() + "lo_")
        A, P = pc.getOperators()
        ctx = P.getPythonContext()
        op = ctx.P1_op
        self.pc.setOperators(op, op)
        self.pc.setUp()
        self.pc.setFromOptions()
        self.transfer = ctx.transfer_op
        self.work1 = self.transfer.createVecLeft()
        self.work2 = self.transfer.createVecLeft()

    def view(self, pc, viewer=None):
        if viewer is not None:
            comm = viewer.comm
        else:
            comm = pc.comm

        PETSc.Sys.Print("Low-order P1, inner pc follows", comm=comm)
        self.pc.view(viewer)

    def apply(self, pc, x, y):
        y.set(0)
        self.work1.set(0)
        self.work2.set(0)
        self.transfer.mult(x, self.work1)
        self.pc.apply(self.work1, self.work2)
        self.transfer.multTranspose(self.work2, y)


import sys

if len(sys.argv) < 2:
    print "Usage: python pulley.py order [petsc_options]"

mesh = Mesh("pulley.msh")

dm = mesh._plex

dm.createLabel("boundary_ids")

sec = dm.getCoordinateSection()
coords = dm.getCoordinates()
def inner_surface(x):
    r = 3.75 - x[2]*0.17
    return (x[0]*x[0] + x[1]*x[1]) < r*r

for f in dm.getStratumIS("exterior_facets", 1).indices:
    p, _ = dm.getTransitiveClosure(f)
    p = p[-3:]
    innerblah = True
    
    for v in p:
        x = dm.vecGetClosure(sec, coords, v)
        if not inner_surface(x):
            innerblah = False
            break
    if innerblah:
        dm.setLabelValue("boundary_ids", f, 1)
    else:
        dm.setLabelValue("boundary_ids", f, 2)

mesh.init()

print "Done initializing the mesh"

# Carry on, subdomain id "1" is on the inner wheel surface
# Subdomain id "2" is the rest of the mesh surface


k = int(sys.argv[1])

V = VectorFunctionSpace(mesh, "CG", k)
bcval = (0, 0, 0)

bcs = DirichletBC(V, bcval, (1,))
u = TrialFunction(V)
v = TestFunction(V)


E = 1.0e9
nu = 0.3
mu = E/(2.0*(1.0 + nu))
lmbda = E*nu/((1.0 + nu)*(1.0 - 2.0*nu))

# Stress computation
def sigma(v):
    return 2.0*mu*sym(grad(v)) + lmbda*tr(sym(grad(v)))*Identity(len(v))


# Define variational problem
u = TrialFunction(V)
v = TestFunction(V)
a = inner(sigma(u), grad(v))*dx

# Rotation rate and mass density
omega = 300.0
rho = 10.0


# Loading due to centripetal acceleration (rho*omega^2*x_i)
fexp = Expression(("rho*omega*omega*x[0]", "rho*omega*omega*x[1]", "0.0"),
               omega=omega, rho=rho)
f = project(fexp, V)
#f = Function(V)

L = inner(f, v)*dx

u0 = Function(V, name="solution")

import time

start = time.time()
SCP = SubspaceCorrectionPrec(a, bcs=bcs)

print 'making patches took', time.time() - start
numpy.set_printoptions(linewidth=200, precision=5, suppress=True)


A = assemble(a, bcs=bcs)

b = assemble(L)

solver = LinearSolver(A, options_prefix="")

A, P = solver.ksp.getOperators()

# Need to remove this bit if don't use python pcs
P = PETSc.Mat().create()
P.setSizes(*A.getSizes())
P.setType(P.Type.PYTHON)
P.setPythonContext(SCP)
P.setUp()
P.setFromOptions()
solver.ksp.setOperators(A, P)

solver.solve(u0, b)


