from types import MethodType
from typing import Optional, Union
from opentrons.types import Location
from opentrons.protocol_api.instrument_context import InstrumentContext
from .TrackedWell import TrackedWell

def init_pipette_for_tracking(pipette):
    """ Function to overwrite aspirate and dispense commands to enable volume tracking of tracked plates"""
    
    #Check if pipette is already initalized for volume tracking
    if not hasattr(pipette, '_vol_tracking'):
        pipette._vol_tracking = True
        #pipette._aspirate = pipette.aspirate
        #pipette._dispense = pipette.dispense

        #Functions with volume tracking
        def aspirate_tracked(self, volume: Optional[float] = None, location: Optional[Union[Location, TrackedWell]] = None, rate: float = 1.0, single_tip_mode=False) -> InstrumentContext:
            """Aspirate liquid from a well, tracking volume if it's a TrackedWell"""
            self.aspirate(volume, location, rate)
            
            if isinstance(location, TrackedWell):
                if 'single' in pipette.name:
                    location.parent.remove_volume(location.well_name, volume)
                
                elif single_tip_mode == True:
                    location.parent.remove_volume(location.well_name, volume)
                
                elif "multi" in pipette.name and single_tip_mode == False:
                    if location.parent.plate_data['plate_type'] == "reservoir":
                        location.parent.remove_volume(location.well_name, 8 * volume) ### Does the Liquid Handling class ppick up less than 8 tips???
                    else:
                        well_col = location.well_name[1:]
                        wells_in_col = location.parent.columns_by_index()[well_col]
                        wells_to_update = wells_in_col[wells_in_col.index(location):] # All wells lower than accessed well in case not row A

                        if location.parent.plate_data['plate_type'] == "384-well":
                            wells_to_update = wells_to_update[::2]
                        
                        for w in wells_to_update:
                            location.parent.remove_volume(w.well_name, volume)
                                    
        
        def dispense_tracked(self, volume: Optional[float] = None, location: Optional[Union[Location, TrackedWell]] = None, rate: float = 1.0, single_tip_mode=False, push_out: Optional[float] = None, ) -> InstrumentContext:
            """Dispense liquid into a well, tracking volume if it's a TrackedWell"""
            self.dispense(volume, location, rate, push_out=push_out)

            if isinstance(location, TrackedWell):
                if 'single' in pipette.name:
                    location.parent.add_volume(location.well_name, volume)
                
                elif single_tip_mode == True:
                    location.parent.add_volume(location.well_name, volume)
                
                elif "multi" in pipette.name and single_tip_mode == False:
                    if location.parent.plate_data['plate_type'] == "reservoir":
                        location.parent.add_volume(location.well_name, 8 * volume) ### Does the Liquid Handling class ppick up less than 8 tips???
                    else:
                        well_col = location.well_name[1:]
                        wells_in_col = location.parent.columns_by_index()[well_col]
                        wells_to_update = wells_in_col[wells_in_col.index(location):] # All wells lower than accessed well in case not row A

                        if location.parent.plate_data['plate_type'] == "384-well":
                            wells_to_update = wells_to_update[::2]
                        
                        for w in wells_to_update:
                            location.parent.add_volume(w.well_name, volume)            
            

        ### To be added
        # Support for transfer and distribute consolidate
                
    
        pipette.aspirate_tracked = MethodType(aspirate_tracked, pipette)
        pipette.dispense_tracked = MethodType(dispense_tracked, pipette)

    else:
        print("Pipette is already initialised for volume tracking")

    return pipette