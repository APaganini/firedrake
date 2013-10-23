import backend

if backend.__name__ == "dolfin":
    solve = backend.fem.solving.solve
    _extract_args = backend.fem.solving._extract_args

else:
    solve = backend.solving.solve

    def _extract_args(*args, **kwargs):
        eq, u, bcs, J, M, form_compiler_parameters, solver_parameters = backend.solving._extract_args(*args, **kwargs)
        return eq, u, bcs, None, None, None, None, solver_parameters
