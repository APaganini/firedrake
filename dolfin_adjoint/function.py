import backend
import ufl
from solving import solve, annotate as solving_annotate
import libadjoint
import assign
import adjlinalg
import adjglobals
import utils

dolfin_assign = backend.Function.assign
dolfin_split  = backend.Function.split
dolfin_str    = backend.Function.__str__
dolfin_interpolate = backend.Function.interpolate

if hasattr(backend.Function, 'sub'):
  dolfin_sub    = backend.Function.sub

def dolfin_adjoint_assign(self, other, annotate=None, *args, **kwargs):
  '''We also need to monkeypatch the Function.assign method, as it is often used inside
  the main time loop, and not annotating it means you get the adjoint wrong for totally
  nonobvious reasons. If anyone objects to me monkeypatching your objects, my apologies
  in advance.'''

  if self is other:
    return

  # ignore anything not a backend.Function, unless the user insists
  if not isinstance(other, backend.Function) and (annotate is not True):
    return dolfin_assign(self, other, *args, **kwargs)

  # ignore anything that is an interpolation, rather than a straight assignment
  if hasattr(self, "function_space") and hasattr(other, "function_space"):
    if str(self.function_space()) != str(other.function_space()):
      return dolfin_assign(self, other, *args, **kwargs)

  to_annotate = utils.to_annotate(annotate)
  # if we shouldn't annotate, just assign
  if not to_annotate:
    return dolfin_assign(self, other, *args, **kwargs)

  other_var = adjglobals.adj_variables[other]
  self_var = adjglobals.adj_variables[self]
  # ignore any functions we haven't seen before -- we DON'T want to
  # annotate the assignment of initial conditions here. That happens
  # in the main solve wrapper.
  if not adjglobals.adjointer.variable_known(other_var) and not adjglobals.adjointer.variable_known(self_var) and (annotate is not True):
    adjglobals.adj_variables.forget(other)
    adjglobals.adj_variables.forget(self)
    if hasattr(other, "split"):
      if other.split is True:
        errmsg = '''Cannot use Function.split() (yet). To adjoint this, we need functionality
        not yet present in DOLFIN. See https://bugs.launchpad.net/dolfin/+bug/891127 .

        Your model may work if you use split(func) instead of func.split().'''
        raise libadjoint.exceptions.LibadjointErrorNotImplemented(errmsg)

    return dolfin_assign(self, other, *args, **kwargs)

  # OK, so we have a variable we've seen before. Beautiful.
  if not adjglobals.adjointer.variable_known(self_var):
    adjglobals.adj_variables.forget(self)

  out = dolfin_assign(self, other, *args, **kwargs)
  assign.register_assign(self, other)
  return out

def dolfin_adjoint_split(self, *args, **kwargs):
  out = dolfin_split(self, *args, **kwargs)
  for i, fn in enumerate(out):
    fn.split = True
    fn.split_fn = self
    fn.split_i  = i
    fn.split_args = args
    fn.split_kwargs = kwargs

  return out

def dolfin_adjoint_str(self):
    if hasattr(self, "adj_name"):
      return self.adj_name
    else:
      return dolfin_str(self)

def dolfin_adjoint_interpolate(self, other, annotate=None):
    out = dolfin_interpolate(self, other)
    if annotate is True:
      assign.register_assign(self, other, op=backend.interpolate)
      adjglobals.adjointer.record_variable(adjglobals.adj_variables[self], libadjoint.MemoryStorage(adjlinalg.Vector(self)))

    return out

if hasattr(backend.Function, 'sub'):
  def dolfin_adjoint_sub(self, idx, deepcopy=False):
      out = dolfin_sub(self, idx, deepcopy=deepcopy)
      out.super_idx = idx
      out.super_fn  = self
      return out

class Function(backend.Function):
  '''The Function class is overloaded so that you can give :py:class:`Functions` *names*. For example,

    .. code-block:: python

      u = Function(V, name="Velocity")

    This allows you to refer to the :py:class:`Function` by name throughout dolfin-adjoint, rather than
    needing to have the specific :py:class:`Function` instance available.

    For more details, see :doc:`the dolfin-adjoint documentation </documentation/misc>`.'''

  def __init__(self, *args, **kwargs):

    annotate = kwargs.pop("annotate", None)
    to_annotate = utils.to_annotate(annotate)

    if "name" in kwargs:
      self.adj_name = kwargs["name"]

      #if self.adj_name in adjglobals.function_names and to_annotate:
      #  backend.info_red("Warning: got duplicate function name %s" % self.adj_name)

      adjglobals.function_names.add(self.adj_name)
      del kwargs["name"]

    backend.Function.__init__(self, *args, **kwargs)

    if hasattr(self, 'adj_name'):
      if backend.__name__ == "dolfin":
        self.rename(self.adj_name, "a Function from dolfin-adjoint")
      else:
        self.name = self.adj_name

    if to_annotate:
      if backend.__name__ == "dolfin":
        function_space_class = backend.cpp.FunctionSpace
      else:
        function_space_class = backend.FunctionSpace
      if not isinstance(args[0], function_space_class):
        if isinstance(args[0], backend.Function):
          known = adjglobals.adjointer.variable_known(adjglobals.adj_variables[args[0]])
        else:
          known = True

        if known or (annotate is True):
          assign.register_assign(self, args[0])

  def assign(self, other, annotate=None, *args, **kwargs):
    '''To disable the annotation, just pass :py:data:`annotate=False` to this routine, and it acts exactly like the
    Dolfin assign call.'''

    return dolfin_adjoint_assign(self, other, annotate=annotate, *args, **kwargs)

  def split(self, *args, **kwargs):
    return dolfin_adjoint_split(self, *args, **kwargs)

  def __str__(self):
    return dolfin_adjoint_str(self)

  def interpolate(self, other, annotate=None):
    if annotate is True and backend.parameters["adjoint"]["stop_annotating"]:
      raise AssertionError("The user insisted on annotation, but stop_annotating is True.")

    return dolfin_adjoint_interpolate(self, other, annotate)

  if hasattr(backend.Function, 'sub'):
    def sub(self, idx, deepcopy=False):
      return dolfin_adjoint_sub(self, idx, deepcopy=deepcopy)

backend.Function.assign = dolfin_adjoint_assign # so that Functions produced inside Expression etc. get it too
if backend.__name__ == "dolfin":
  backend.Function.split  = dolfin_adjoint_split
backend.Function.__str__ = dolfin_adjoint_str
backend.Function.interpolate = dolfin_adjoint_interpolate

if hasattr(backend.Function, 'sub'):
  backend.Function.sub = dolfin_adjoint_sub
