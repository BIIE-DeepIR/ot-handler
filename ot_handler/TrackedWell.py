from typing import Any, Dict
import types
from opentrons.protocol_api.labware import Well

class TrackedWell(Well):
    """A well wrapper that updates volumes in the parent Plate and maintains Well type compatibility"""
    
    def __init__(self, physical_well, parent_plate):
        # Get the well's underlying implementation
        self._well = physical_well
        self._plate = parent_plate

        # Call parent Well's __init__ with the physical well's implementation details
        super().__init__(
            parent=physical_well._parent,
            core=physical_well._core,
            api_version=physical_well._api_version
        )

        # Define methods/properties that should not be copied
        excluded_methods = {
            # Tip rack specific methods
            'geometry',
            # Parent method
            'parent'
         }
        
        # Copy all attributes from physical well that aren't already handled by Well
        for attr_name in dir(physical_well):
            if not attr_name.startswith('_') and attr_name not in excluded_methods and not hasattr(self, attr_name):
                print(attr_name)
                try:
                    attr = getattr(physical_well, attr_name)
                    if isinstance(attr, types.MethodType):
                        setattr(self, attr_name, attr)
                    else:
                        setattr(self, attr_name, attr)
                except AttributeError:
                    pass

    
    @property
    def parent(self):
        """Return the Plate instance instead of labware"""
        return self._plate
    
    def __repr__(self):
        return self._well.__repr__()
    
    def __str__(self):
        return self._well.__str__()