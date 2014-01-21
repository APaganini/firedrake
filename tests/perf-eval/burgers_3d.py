"""This demo program solves Burgers' equation"""

from firedrake import *

def run_burgers(n=30, degree=1):
    mesh = UnitCubeMesh(2**n, 2**n, 2**n)
    V = VectorFunctionSpace(mesh, "CG", degree)

    ic = project(Expression(["sin(pi*x[0])", 0, 0]), V)

    u_ = Function(ic, name="Velocity")
    u = Function(V, name="VelocityNext")
    v = TestFunction(V)

    u_.assign(ic)
    u.assign(ic)

    nu = 0.0001

    timestep = 1.0/n

    F = (inner((u - u_)/timestep, v)
         + inner(u, dot(grad(u), v)) + nu*inner(grad(u), grad(v)))*dx
    #bc = DirichletBC(V, [0.0, 0.0], 1)

    #outfile = File("burgers.pvd")
    #outfile << u

    #t = 0.0
    #end = 0.2
    #while (t <= end):
        #print t
    solve(F == 0, u)
            #, solver_parameters={'snes_view': True, 'snes_converged_reason': True, 'ksp_converged_reason': True, 'snes_linesearch_monitor': True, 'snes_monitor': True, 'ksp_monitor_true_residual': True})
    #    u_.assign(u)
    #    t += timestep
        #outfile << u

    return u
