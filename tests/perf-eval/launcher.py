import pyop2.ir.ast_plan as ap

import sys
import cProfile
import pstats
import os

opts = ['NORMAL', 'LICM', 'LICM_AP', 'LICM_AP_TILE', 'LICM_AP_VECT']
problems = ['HELMHOLTZ']


if len(sys.argv) in [2, 3]:
    if len(sys.argv) == 3 and sys.argv[2] in problems:
        problem = sys.argv[2]
    else:
        problem = problems[0]

    if sys.argv[1] == '--help':
        _opts = "\n".join(["- %s" % i for i in opts])
        print "Possible optimisations are:\n" + _opts
        sys.exit(0)
    else:
        opt = sys.argv[1] if sys.argv[1] in opts else 'ALL'
else:
    opt = 'ALL'
    problem = problems[0]

if problem == 'HELMHOLTZ':
    from helmholtz import run_helmholtz as run_prob


### RUN PROBLEM ###

mesh_size = 5
poly_order = 2
results = []

if opt in ['ALL', 'NORMAL']:
    print "Run NORMAL Helmholtz"
    cProfile.run("results.append(run_prob(mesh_size, poly_order))", 'cprof.NORMAL.dat')
    print "*****************************************"
    p = pstats.Stats('cprof.NORMAL.dat')
    p.sort_stats('time').print_stats(10)
    print "*****************************************\n\n"


if opt in ['ALL', 'LICM']:
    print "Run LICM Helmholtz"
    os.environ['PYOP2_IR_LICM'] = 'True'
    cProfile.run("results.append(run_prob(mesh_size, poly_order))", 'cprof.LICM.dat')
    print "*****************************************"
    p = pstats.Stats('cprof.LICM.dat')
    p.sort_stats('time').print_stats(10)
    print "*****************************************\n\n"


if opt in ['ALL', 'LICM_AP']:
    print "Run LICM+ALIGN+PADDING Helmholtz"
    os.environ['PYOP2_IR_AP'] = 'True'
    os.environ['PYOP2_IR_VECT'] = '((%s, 2), "avx", "intel")' % ap.AUTOVECT
    cProfile.run("results.append(run_prob(mesh_size, poly_order))", 'cprof.LICM_AP.dat')
    print "*****************************************"
    p = pstats.Stats('cprof.LICM_AP.dat')
    p.sort_stats('time').print_stats(10)
    print "*****************************************\n\n"


if opt in ['ALL', 'LICM_AP_VECT']:
    print "Run LICM+ALIGN+PADDING+VECT Helmholtz"
    os.environ['PYOP2_IR_VECT'] = '((%s, 2), "avx", "intel")' % ap.V_OP_UAJ
    cProfile.run("results.append(run_prob(mesh_size, poly_order))", 'cprof.LICM_AP_VECT.dat')
    print "*****************************************"
    p = pstats.Stats('cprof.LICM_AP_VECT.dat')
    p.sort_stats('time').print_stats(10)
    print "*****************************************\n\n"

