__version__ = "0.6.2"

import numpy

# opentrons_shared_data (through 10.0 alpha) imports numpy.trapz, removed in numpy 2.4.
if not hasattr(numpy, "trapz"):
    numpy.trapz = numpy.trapezoid

from .liquid_handler import LiquidHandler as LiquidHandler
