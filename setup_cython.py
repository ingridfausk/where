from distutils.core import setup
from Cython.Build import cythonize
import numpy as np
import sys


# Hack sys.argv before sending to setup
sys.argv[1:] = ["build_ext", "--inplace"]

sourcefiles = ["where/models/orbit/*.pyx", "where/integrators/*.pyx"]
# Setup each version
setup(
    name="cython_orbit_models",
    include_dirs=[np.get_include()],
    ext_modules=cythonize(
        sourcefiles,
        language_level=3,
        annotate=True,
        compiler_directives={
            "boundscheck": False,
            "cdivision": True}
    ),
)
